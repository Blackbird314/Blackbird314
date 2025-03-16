+++
title = "Rust 核心编程：生命周期"
date = "2024-07-09T19:09:18+08:00"
tags = ["Rust"]
slug = "rust-lifetimes"
+++

## 什么是生命周期

生命周期(Lifetimes)是 Rust 独有的一个概念，借用检查通过它跟踪所有权和借用之间的关系，从而保证内存安全。生命周期具有许多微妙之处：

Rust 为每个引用都分配一个生命周期，这是引用保持有效的一段代码区域，而借用检查限制你只能在这个范围内访问该引用。更具体的说，所有持有或包含引用的变量/表达式，都具有一个生命周期，该生命周期是其类型的一部分。生命周期可能很复杂，甚至未必是连续的代码区域，因为你可以先让一个引用失效，再重新初始化并使用它：

```Rust
// r 的生命周期 'r 是不连续的区间
let mut r: &'r i32;

{
    let x = 128;
    'r: {
        r = &x;
        println!("{r}");
    }
}

// 此处引用 r 失效

{
    let y = 256;
    'r: {
        r = &y;
        println!("{r}");
    }
}
```

这里说的“保持有效”，是针对引用的地址值，而非持有它的变量或表达式，变量仍需遵守作用域规则（所谓“非词法生命周期”）。多数情况下，变量作用域和引用的生命周期重合，因为编译器..总是试图最小化生命周期的范围..；但变量离开作用域后，它持有的引用仍可能保持有效，这时引用的生命周期可能被延长至超过变量作用域：

```Rust
// r1 生命周期被推断为最小的 'a，与作用域重合
'a: {
    let r1: &'a str = "Hello";
    println!("{r1}");
}

// r2 生命周期可以被手动标注为 'static，超过了作用域
let r2: &'static str = "World";
println!("{r2}");

// r3 生命周期不能是 'static，编译失败！
let r3: &'static str = &String::from("Hello, world!");
```

生命周期推断和检查的核心规则只有一点：..引用的生命周期不能超过引用对象的生存期..(Liveness)

这个规则很直观，若一个引用的生命周期为 `'a`，那么它指向对象的生存期必然不小于 `'a`。所以编译器允许将 `r2` 标注为 `'static`，不允许 `r3` 拥有 `'static` 生命周期。

若有一个指向引用的引用 `&'a &'b T`，我们会得到：`'a` ≤ liveness(`&'b T`) ≤ `'b`。反过来说，要构造一个 `&'a &'b T`，仅有 `'a` ≤ `'b` 是不够的：

```Rust
let r: &'static str = "Hello, world!";
// rr 生命周期不能是 'static，编译失败！
let rr: &'static &'static str = &r;
```

重借用表达式 `&*r` 的生命周期取决于原始引用 `r` 的生命周期，而非 `*r` 的实际生存期，因为生命周期语义的限制，我们只能在 `r` 的生命周期内访问 `r`。

Rust 实际上不允许命名具体的生命周期，上述 `&'r i32` `&'a str` 不是合法的语法。一般来说，Rust 可以自行推断所需的生命周期，只有跨越函数的边界传递引用，情况才会变得复杂。譬如借用检查如何避免返回悬垂引用？答案是比较函数签名返回值和实际返回值的生命周期：

```Rust
fn return_str<'a>() -> &'a str {
    'b: {
        let s = String::from("data");
        &s
    }
}
```

`return_str()` 函数会返回一个具有 `'a` 生命周期的引用。不同于前面的伪代码，`<'a>` 表明这是一个..泛型生命周期..，每次调用 `return_str()` 时，都会单态化(monomorphization)得到一个具体的生命周期 `'a`，并反映在返回类型中。注意，对于没有显示约束的泛型类型 `<T>`，编译器会自动添加 `T: Sized` 约束，同理 `'a` 并不是可以任意小的生命周期，编译器要求它..必须包含函数调用本身..。

实际返回的表达式 `&s`，其生命周期不能超过局部变量 s 的生存期 `'b`，显然这与函数签名矛盾，Rust 认为 `return_str()` 函数会导致悬垂引用。

泛型生命周期标注还可用于函数参数或局部变量：

```Rust
fn get_str<'a>(mut r: &'a str) { // 泛型标注 'a 可以省略，但不改变编译结果
    println!("{r}");
    'b: {
        let s = String::from("data"); // `s` does not live long enough
        r = &s;
        println!("{r}");
    } // `s` dropped here while still borrowed
}
```

编译 `get_str()` 函数会报错，因为参数 `r` 的生命周期 `'a` 应包含整个函数调用，而表达式 `&s` 的生命周期不超过 `'b`，所以 Rust 认为 `get_str()` 函数不安全。但若仔细分析 `get_str()`，发现它其实不会破坏内存安全，看得出 Rust 借用检查过于严苛了。此处，生命周期的局限性已初见端倪。

让我们继续深入跨越函数的生命周期，函数签名实际上将代码分成了两个世界：函数定义和函数调用。借用检查不会跨越函数进行分析，它首先检查函数定义，假定形参和局部变量拥有签名标注的生命周期，计算返回表达式的生命周期，确保与函数签名吻合；然后检查函数调用，确保传入的实参和调用结果满足函数签名：

```Rust
// 函数定义
fn transfer_str<'a>(parameter: &'a str) -> &'a str { // 已知参数 parameter 具有某个生命周期 'a
    let result: &'a str = parameter;
    result // 计算返回表达式 result 的生命周期为 'a，满足函数签名
}

fn main() {
    let s = String::from("Hello, world!");
    let argument = &s;
    // 函数调用
    let r: &'static str = transfer_str(argument); // 编译失败
}
```

`transfer_str()` 的返回值与函数签名一致，但函数调用的结果被赋值给具有 `'static` 生命周期的 `r`，这要求本次调用的 `'a` 单态化为 `'static`，但入参 `argument` 的生命周期显然不能是 `'static`。

生命周期还和借用规则有千丝万缕的联系，考虑这个例子：

```Rust
let mut data = vec![1, 2, 3];
let x = &data[0];
data.push(4);
println!("{}", x);
```

我们希望 Rust 拒绝这个程序，理由是共享引用 `x` 指向 `data` 的一个子集，而我们试图对 `data` 本身借可变引用，这违反了第二条借用规则。但借用检查并不理解“子集”这个概念，它对索引操作解糖后看到的是 `Index::index` 方法调用：

```Rust
let mut data: Vec<i32> = vec![1, 2, 3];
'x: {
    let x: &'x i32 = Index::index::<'x>(&'x data, 0); // 'x 这个生命周期范围如我们所愿地小（刚好够 println!）
    'a: {
        Vec::push(&'a mut data, 4); // 这里有一个临时作用域 'a，我们不需要更长时间的 &mut 借用
    }
    println!("{}", x);
}
```

由于 `x` 的生命周期被推断为 `'x`，根据方法签名，入参 `&data` 的生命周期也被推断为 `'x`，这与生命周期为 `'a` 的 `&mut data` 冲突，于是报错。

## 子类型化与型变

原生的生命周期实现要么过于严格，要么会允许未定义行为。为了使借用检查更灵活，Rust 生命周期支持子类型化(Subtyping)。

在编程语言理论中，子类型化是一种类型多态的形式，它允许用子类型(Subtype)替换相应的父类型(Supertype)。也就是说，针对父类型对象进行的操作，相应的子类型对象也适用。Wikipedia 对其有如下解释：

> If `Sub` is a subtype of `Super`, the subtyping relation (written as `Sub` <: `Super`) means that any term of type `Sub` can safely be used in any context where a term of type `Super` is expected.

子类型化常见于支持继承的语言(C#/Java)，例如 `Cat` 继承自 `Animal`，那么直觉上很容易想到，任何需要 `Animal` 类型的表达式，都可以用 `Cat` 去替换，所以说 `Cat` 是 `Animal` 的子类型。Rust 没有继承，它只对生命周期采用子类型化。以下代码允许将生命周期更长的 `s` 赋值给生命周期较短的 `t`，这背后是子类型化在起作用：

```Rust
fn bar<'a>() {
    let s: &'static str = "hi";
    let t: &'a str = s; // 编译成功
}
```

_Rustonomicon_ 对生命周期父子关系的解释是：

> 当且仅当 `'long` 完全包含 `'short` 时，定义 `'long` 是 `'short` 的子类型，写作 `'long` <: `'short`。

乍看上去有点反直觉，但正如 `Cat` 拥有 `Animal` 的所有属性和方法，`'long` 也包含了 `'short` 定义的全部区域。通俗地讲，子类型是在父类型的基础上拓展得来，它比父类型具有更多的“内涵” ———— 所谓“子生于父而胜于父”。

子类型化大大增强了生命周期的灵活性，若没有子类型化，以下代码甚至无法编译：

```Rust
// debug 需要两个具有相同生命周期的参数
fn debug<'a>(a: &'a str, b: &'a str) {
    println!("a = {a:?} b = {b:?}");
}

fn main() {
    let hello: &'static str = "hello";
    {
        let world = String::from("world");
        let world = &world; // 生命周期 'world 比 'static 短
        debug(hello, world); // hello 被隐式地从 `&'static str` 裁减为 `&'world str`
    }
}
```

Rust 支持生命周期约束语法，`'a: 'b` 的意思是 `'a` outlives `'b`，这代表着 `'a` <: `'b`。可问题在于，Rust 中 `'a` 并不是一种单独的类型，它只能作为类型的一部分出现。若有 `'a` <: `'b`，那么对于生命周期构造出的类型，如 `&'_ T`，也应该有 `&'a T` :< `&'b T` 吗？解答这个问题，首先要理解型变(Variance)概念。

型变是类型构造器(Type Constructors)具有的一个属性，用来说明在子类型的层面上，构造器的输入如何影响它的输出。类型构造器是一个表示为 `F<T>` 的泛型类型，例如 `Vec` 接受一个泛型 `T` 的输入，返回 `Vec<T>`；`&` `&mut` 接受泛型 `'a` 和 `T` 的输入，返回 `&'a T` `&'a mut T`。Rust 中有三种型变，给定 `Sub` 是 `Super` 的子类型：

- `F<T>` 协变(Covariant)，如果 `F<Sub>` 是 `F<Super>` 的子类型（子类型关系被继承）
- `F<T>` 逆变(Contravariant)，如果 `F<Super>` 是 `F<Sub>` 的子类型（子类型关系被反转）
- `F<T>` 不变(Invariant)，如果 `F<Sub>` 与 `F<Super>` 不存在子类型关系

为了兼顾安全与灵活，Rust 语言团队设计了一套型变规则：

|  **`F<'a, T, U>`**  | **`'a`** | **`T`** | **`U`** |
| :-----------------: | :------: | :-----: | :-----: |
|       `&'a T`       |   协变   |  协变   |         |
|     `&'a mut T`     |   协变   |  不变   |         |
|     `*const T`      |          |  协变   |         |
|      `*mut T`       |          |  不变   |         |
|   `UnsafeCell<T>`   |          |  不变   |         |
|  `[T]` 和 `[T; n]`  |          |  协变   |         |
|      `Box<T>`       |          |  协变   |         |
|  `PhantomData<T>`   |          |  协变   |         |
|    `fn(T) -> U`     |          |  逆变   |  协变   |
| `dyn Trait<T> + 'a` |   协变   |  不变   |         |

某些类型的型变规则，可参照其他类型简单阐明：

- `Vec<T>` 和其它拥有型指针遵循与 `Box<T>` 一致的型变逻辑 这在其它语言中不安全
- `*const T` `*mut T` 分别遵 `&T` `&mut T` 的型变逻辑
- `UnsafeCell<T>` 具有内部可变性，因而其型变规则与 `&mut T` 相同
- `Cell<T>` 和其它内部可变类型遵循与 `UnsafeCell<T>` 一致的型变逻辑
- 函数指针类型 `fn(V) -> V` 对 `V` 是不变的

`&'a T` `&'a mut T` 对 `'a` 协变，直觉上这很好理解：任何需要一个短生命周期引用 `&'short T` 的地方，传入一个长生命周期引用 `&'long T` 总是安全的。可为什么 `&mut T` 对 `T` 不变？

```Rust
fn assign<T>(input: &mut T, val: T) {
    *input = val;
}

fn main() {
    let mut r: &'static str = "hello";
    let world = String::from("world");
    'a: { // &world 生命周期为 'a
        assign(&mut r, &world);
    }
    println!("{r}"); // 使用了悬垂引用 r！
}
```

`assign` 会将 `r` 修改为指向 `world` 的引用，而 `world` 在打印时已被释放，这是一个典型的悬垂引用。幸运的是，这段代码无法编译，因为即使 `&'static str` 是 `&'a str` 的子类型，`&mut &'static str` 也不能是 `&mut &'a str` 的子类型，

## 高阶特型约束(HRTB)

## Early bound vs Late bound

## 生命周期的新进展 Polonius
