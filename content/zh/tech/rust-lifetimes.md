+++
title = "Rust 核心语法：非词法生命周期"
date = "2024-07-09T19:09:18+08:00"
tags = ["Rust"]
description = "The Dark Arts that corrode souls"
slug = "rust-lifetimes"
+++

## 什么是生命周期

借用检查(Borrow Check)的核心理念是：当内存处于借用状态时，其本身不能被修改、移动或释放。为了追踪所有者和借用的关系，Rust 提出了生命周期(Lifetimes)的概念：每次借用，编译器都会为生成的引用赋予一个生命周期，它对应着引用可能被访问的代码区间。编译器会通过推断算法，确定一个能覆盖所有引用使用的最小生命周期。

> 注意：引用的生命周期不是值的生存期，后者对应值从创建到释放的时间跨度。为了区分，我们将这个时间跨度称为值的作用域。

生命周期分析基于以控制流图(CFG)表示的 [MIR](https://blog.rust-lang.org/2016/04/19/MIR.html)，而非以抽象语法树(AST)表示的 HIR。具体来说，生命周期被定义为 MIR 控制流图中一系列节点的集合，如果生命周期包含点 `P`，说明引用在 `P` 点处有效；在下文中，我们会进一步扩展这个定义，以涵盖 "Skolemized" 生命周期 —— 对应于函数定义中的具名生命周期。

生命周期出现在 MIR 的以下位置：

1. 持有引用的变量或临时变量，其类型中包含生命周期
2. 每个借用表达式都有一个指定的生命周期

下例的伪代码会产生三个生命周期，我们将其命名为 `'p` `'foo` `'bar`：

```Rust
let mut foo: T = ...;
let mut bar: T = ...;
let mut p: &'p T;

p = &'foo foo;
// P0
if condition {
    print(*p);
    // P1
    p = &'bar bar;
    // P2
}
// P3
print(*p);
// P4
```

如你所见，`'p` 是变量 `p` 类型的一部分，它表示在控制流图的哪些部分可以安全地对 `p` 进行解引用；生命周期 `'foo` 和 `'bar` 来自借用表达式，它们分别表示 `foo` 和 `bar` 被借用的有效时段。

借用表达式的生命周期是借用检查的基石。在本例中，编译器对 `'foo` `'bar` 涵盖的控制流施加限制：

1. 在对应生命周期结束前，`foo` 和 `bar` 不能被移动或释放
2. 由于 `&foo` `&bar` 均为共享借用，借用检查器将阻止在对应生命周期内修改 `foo` 和 `bar`；若为可变借用，借用检查器将阻止在对应生命周期内访问 `foo` 和 `bar`

## 生命周期推断

为了推断 `'p` `'foo` `'bar`，编译器将示例代码转换为控制流图。其中节点 `A0` `B2` `C0` 分别对应 `p = &foo` `p = &bar` `print(*p)`：

```Rust
let mut foo: i32;
let mut bar: i32;
let mut p: &i32;

A
[ p = &foo     ] // A0
[ if condition ] ----\ (true)
       |             |
       |     B       v
       |     [ print(*p)     ]
       |     [ ...           ]
       |     [ p = &bar      ] // B2
       |     [ ...           ]
       |     [ goto C        ]
       |             |
       +-------------/
       |
C      v
[ print(*p)    ] // C0
[ return       ]
```

### 基于活性的约束

借用检查器首先计算变量的活性(Liveness)：若某个变量当前持有的值可能在后续程序中被使用，我们则称该变量处于存活状态。变量 `p` 在 `A0` 处被赋值，在 `B2` 处重新赋值，在 `B0` 和 `C0` 处被使用。关键在于，`p` 在 `B1` 处持有的值 `&foo`，后续不再使用，所以 `p` 在 `B1` 处为死亡状态。特别注意，变量赋值后才持有值，因此 `p` 在 `A0` `B2` 处同样被视为死亡状态，这个设定在求解生命周期约束时很有用。

接着基于活性计算生命周期：若变量 `p` 在点 `P` 处存活，且生命周期 `'p` 出现在 `p` 的类型中，则 `'p` 包含点 `P`。

于是得到：

```Rust
'p = {A1, B0, B3, B4, C0}
```

对应到源代码：

```Rust
'p = {P0, P2, P3}
```

MIR 还包含一个析构变量的操作 `DROP(variable)`，它同样会导致变量活性的延长。有趣的是，此时变量的存活..不一定扩大对应生命周期的范围..。例如 `&'a T` `&'a mut T` 的析构是空操作，引用有效与否并不重要，在此类情况下，我们称生命周期 `'a` 在析构时可以悬垂；而对于实现了 `Drop` 的类型 `F<'a>`，`'a` 在析构时通常不能悬垂。

具体来说，[RFC 1327](https://rust-lang.github.io/rfcs/1327-dropck-param-eyepatch.html) 定义了哪些生命周期在析构时可以悬垂。因而在计算生命周期时，我们再追加一条规则：即使变量当前持有的值在未来可能被 `DROP`，其类型中被规定为"可以悬垂"的生命周期不必包含当前节点。

由此看出，和词法作用域相比，生命周期要灵活得多，甚至可以存在“空洞”（不连续的代码区间），因此 [RFC 2094](https://rust-lang.github.io/rfcs/2094-nll.html) 称其为非词法生命周期(Non-lexical lifetimes)。

生命周期 `'foo` 和 `'bar` 未出现在任何变量类型中，故不存在（直接）存活的节点。

### 子类型化约束

在编程语言理论中，子类型化(Subtyping)是一种类型多态的形式，它允许用子类型(Subtype)替换相应的父类型(Supertype)。也就是说，针对父类型对象进行的操作，相应的子类型对象也适用。Wikipedia 对其有如下解释：

> If `Sub` is a subtype of `Super`, the subtyping relation (written as `Sub` <: `Super`) means that any term of type `Sub` can safely be used in any context where a term of type `Super` is expected.

子类型化常见于支持继承的语言(C#/Java)，例如 `Cat` 继承自 `Animal`，那么直觉上很容易想到，任何需要 `Animal` 类型的表达式，都可以用 `Cat` 去替换，所以说 `Cat` 是 `Animal` 的子类型。Rust 没有继承，它只对生命周期采用子类型化。

_Rustonomicon_ 对生命周期父子关系的解释：

> 当且仅当 `'a` 包含(outlives) `'b` 时，我们定义 `'a` 是 `'b` 的子类型，写作 `'a: 'b`。

乍看上去有点反直觉，但正如 `Cat` 拥有 `Animal` 的属性和方法，`'a` 也包含了 `'b` 定义的节点：子类型是在父类型的基础上拓展得来，它比父类型具有更多的“内涵”。

死灵书的解释并不严谨，非词法生命周期的子类型化实际是位置敏感(location-aware)的 —— 判定时需要考虑子类型化的具体位置。例如，在程序点 `A0` 处，借用表达式 `&foo` 生成一个 `&'foo T` 类型的引用，该引用被赋予 `&'p T` 类型的变量 `p`。因此，我们需要确保 `&'foo T` 是 `&'p T` 的子类型。此外，这种子类型关系只需在赋值发生点的后继节点 `A1` 处成立（因为 `p` 的新值在 `A1` 点才首次可见）。

于是得到如下子类型约束：

```Rust
(&'foo T <: &'p T) @ A1
(&'bar T <: &'p T) @ B3
```

依据型变规则，它们被转换为生命周期约束：

```Rust
('foo: 'p) @ A1
('bar: 'p) @ B3
```

### 重借用约束

还有一类约束的来源是重借用。

为定义重借用约束，我们首先引入 _Supporting prefixes_ 的概念。左值(lvalue)的 _Supporting prefixes_ 通过剥离解引用与字段构成，直到得到共享引用的解引用时停止剥离。以下列举若干支持性前缀的示例：

```Rust
let r: (&(i32, i64), (f32, f64));

左值 (*r.0).1 的 supporting prefixes:
- (*r.0).1
- *r.0

左值 r.1.0 的 supporting prefixes:
- r.1.0
- r.1
- r

let m: (&mut (i32, i64), (f32, f64));

左值 (*m.0).1 的 supporting prefixes:
- (*m.0).1
- *m.0
- m.0
- m
```

然后考虑对表达式 `lvalue` 的借用；

```Rust
r = &'b lvalue;
// P

r = &'b mut lvalue;
// P
```

在此情形下，我们计算 `lvalue` 的 _Supporting prefixes_ 集合，并寻找集合中所有解引用 `*lv`（让我们称 `lv` 的生命周期为 `'a`）；然后添加生命周期约束 `('a: 'b) @ P`，其中 `P` 为借用开始生效的节点。

关于解引用约束的更多示例见[Reborrow constraints](https://rust-lang.github.io/rfcs/2094-nll.html#reborrow-constraints)。

### 约束求解

约束条件生成后，编译器通过定点迭代法求解这些约束：每个生命周期初始化为空集，随后遍历约束条件并不断扩展生命周期范围，直至满足所有约束。

形如 `('a: 'b) @ P` 的约束条件意味着：从点 `P` 出发，生命周期 `'a` 必须包含 `'b` 中所有可从 `P` 到达的点。具体实现时，编译器从 `P` 点开始对 `'b` 进行[深度优先搜索]()，通过遍历 CFG 中可能的代码路径，将搜索到的每个有效节点添加至 `'a` 集合中；若搜索过程超出生命周期 `'b` 范围，则退出该条路径的搜索。例如，本例中从 `A1` 可以到达 `B0` 和 `C0`，却不能到达 `B3` `B4`（`'p` 存在空洞，搜索到 `B1` 节点则退出 `if` 路径）。

求解上述约束得到：

```Rust
'p = {A1, B0, B3, B4, C0}
'foo = {A1, B0, C0}
'bar = {B3, B4, C0}
```

## 具名生命周期

截至目前，我们仅讨论了函数作用域内的借用问题，编译器可以自动推理相关生命周期。当跨越函数的边界传递引用时，需要开发者显式标注生命周期。除 `'static` 外，Rust 只允许以 `<'r>` 语法声明..泛型生命周期..。每次函数调用或类型实例化，`'r` 都会单态化(_monomorphization_)为一个具体的代码区间。

特别的，函数定义涉及的具名生命周期（如 `'r`）被定义为至少包含以下要素的集合：

- 当前函数 CFG 的全部节点
- `end('r)` —— 函数返回后调用者（或调用者的调用者...）的某些节点

<!-- 可能为空集 -->

然后调整生命周期约束的定义，以涵盖具名生命周期。具体而言，`('a: 'b) @ P` 的语义被扩展为：当 `'b` 可从 `P` 到达当前函数 CFG 的终点时，将 `'b` 包含的所有 `end('_)` 添加至 `'a`。考虑以下示例：

```Rust
fn foo<'a, 'b>(x: &'a u32, y: &'b u32) -> &'b u32 {
    x // 编译失败
}
```

根据泛型生命周期的定义，我们得到：

```Rust
// F 表示 foo 函数体
'a = {F, end('a)}
'b = {F, end('b)}
```

返回的表达式 `x` 要求 `&'a u32` <: `&'b u32`，从而产生一个生命周期约束 `'a: 'b`，这要求我们将 `end('b)` 加入 `'a`，得到 `'a = {F, end('a), end('b)}`。

最后，编译器执行检查：若某个泛型生命周期 `'a` 包含元素 `end('b)`，则必须有 `where` 子句或隐含约束说明 `'a: 'b`，否则报错。

<!-- 函数声明实际上将代码分成了两个部分：函数定义和函数调用。 -->

借用检查不会跨函数进行分析，它分别检查函数定义和函数调用，考虑下例：

```Rust
let mut data = vec![1, 2, 3];
let x = &data[0];
data.push(4);
println!("{}", x);
```

我们希望 Rust 拒绝这个程序，理由是共享引用 `x` 指向 `data` 的一个子集，而我们试图对 `data` 本身借可变引用。但借用检查器并不理解“子集”的概念，它对索引操作解糖后看到的是一个 `Index::index` 函数调用：

```Rust
let mut data: Vec<i32> = vec![1, 2, 3]; // L1
let x: &i32 = Index::index(&data, 0); // L2
Vec::push(&mut data, 4); // L3
println!("{}", x); // L4
```

`x` 的生命周期被推断为 `{L3, L4}`，根据 `Index::index` 函数签名和子类型化约束，借用表达式 `&data` 的生命周期也被推断为 `{L3, L4}`，这与生命周期为 `L3` 的 `&mut data` 冲突，于是报错。

关于编译器内置的静态生命周期 `'static`，它的语义是..到程序结束保持有效..。与 `'a` 类似，`'static` 包括一个表示为 `end('static)` 的元素，对应当前函数返回后程序执行的剩余部分。

字符串字面值在程序运行期间始终有效，所以它的引用类型可以是 `&'static str`。这里存在一种误解，认为 `'static` 引用的对象必须在编译时创建且不可变。但以内存泄漏为代价，我们可以得到指向运行时内存的 `&'static mut T` 引用：

```Rust
use rand;

// 在运行时生成随机 &'static str
fn rand_str_generator() -> &'static str {
    let rand_string = rand::random::<u64>().to_string();
    Box::leak(rand_string.into_boxed_str())
}
```

`'static` 是任何生命周期的子类型，可以将 `s` 赋值给 `t`，因为满足约束 `('static: 'a) @ L3`：

```Rust
fn bar<'a>() {
    let s: &'static str = "hi";
    let t: &'a str = s;
    // L3
}
```

## 型变

生命周期的子类型化引入了一个新的问题：若 `'sub` <: `'super`，那么对于生命周期构造出的类型 `F<'_>`，也应该有 `F<'sub>` :< `F<'super>` 吗？回答这个问题，首先要理解型变的概念。

型变(Variance)是类型构造器(Type constructor)具有的一个属性，用来说明简单类型的父子关系如何决定复合类型的父子关系。类型构造器是一个表示为 `F<T>` 的泛型类型，例如 `Vec` 接受一个泛型 `T` 的输入，返回 `Vec<T>`；`&` `&mut` 接受泛型 `'a` 和 `T` 的输入，返回 `&'a T` `&'a mut T`。Rust 中有三种型变，给定 `Sub` 是 `Super` 的子类型：

- `F<T>` 协变(Covariant)，如果 `F<Sub>` 是 `F<Super>` 的子类型（子类型关系被传递）
- `F<T>` 逆变(Contravariant)，如果 `F<Super>` 是 `F<Sub>` 的子类型（子类型关系被反转）
- `F<T>` 不变(Invariant)，如果 `F<Sub>` 与 `F<Super>` 不存在子类型关系

为了兼顾安全与灵活，Rust 语言团队设计了一套型变规则：

|  **`F<'a, T, U>`**   | **`'a`** | **`T`** | **`U`** |
| :------------------: | :------: | :-----: | :-----: |
|       `&'a T`        |   协变   |  协变   |         |
|     `&'a mut T`      |   协变   |  不变   |         |
|      `*const T`      |          |  协变   |         |
|       `*mut T`       |          |  不变   |         |
|   `UnsafeCell<T>`    |          |  不变   |         |
|  `[T]` 和 `[T; n]`   |          |  协变   |         |
|       `Box<T>`       |          |  协变   |         |
|   `PhantomData<T>`   |          |  协变   |         |
|     `fn(T) -> U`     |          |  逆变   |  协变   |
| `dyn Trait<T> + 'a`  |   协变   |  不变   |         |

某些类型的型变规则，可参照其他类型简单阐明：

- `Vec<T>` 和其它容器类型遵循与 `Box<T>` 一致的型变逻辑
- `*const T` `*mut T` 分别遵循 `&T` `&mut T` 的型变逻辑
- `UnsafeCell<T>` 具有内部可变性，因而其型变规则与 `&mut T` 相同
- `Cell<T>` 和其它内部可变类型遵循与 `UnsafeCell<T>` 一致的型变逻辑

`&'a T` `&'a mut T` 对 `'a` 协变，这符合我们的直觉：任何需要一个短生命周期引用 `&'short T` 的地方，传入一个有效期更长的引用 `&'long T` 总是安全的。可为什么 `&mut T` 对 `T` 是不变的？

若将其视为对 `T` 协变，由于 `&mut T` 对 `T` 是可写的，导致我们可以把一个短生命周期的引用写入长生命周期的引用，从而引发安全问题。考虑以下代码：

```Rust
fn assign<T>(input: &mut T, val: T) {
    *input = val;
}

fn main() {
    let mut ptr: &'static str = "hello";
    {
        let world = String::from("world");
        assign(&mut ptr, &world); // &world 有一个临时生命周期 'a
    }
    println!("{ptr}"); // 悬垂引用 ptr
}
```

`assign` 通过对 `ptr` 借可变引用，使它重新指向 `world`，然而 `ptr` 的生命周期是 `'static`，在 `world` 被释放后打印 `ptr` 导致了未定义行为。为避免这种情况，`&mut &'static str` 不能是 `&mut &'a str` 的子类型。

类似的，由于 `&mut T` 对 `T` 是可读的，若对 `T` 逆变会扩张 `T` 的有效期，也会导致悬垂引用。而 `&T` 对 `T` 是只读的，因此可以对 `T` 协变，不能对 `T` 逆变。

然而 `&mut T` 和 `Box<T>` 都是指向 `T` 的可读写指针，为什么后者对 `T` 可以是协变？因为子类型化发生时，所有权机制使旧的 `Box<T>` 在移动后失效，并保证它拥有的值不被第三者借用。这是 Rust 的优势，同样的设计在其他语言中是不安全的。

<!-- 这大概是为什么 &*r 会移除 r 的所有权 -->

下面的示例很好地说明了这一点：

```Rust
fn assign<T>(mut input: Box<T>, val: T) {
    *input = val;
}

fn main() {
    let boxed_ptr: Box<&'static str> = Box::new("hello");
    {
        let world = String::from("world");
        assign(boxed_ptr, &world); // boxed_ptr 子类型化的同时传入所有权
    }
    println!("{boxed_ptr}"); // boxed_ptr 已失效
}
```

`assign` 调用后，我们销毁了唯一记得 `'static` 生命周期的 `boxed_ptr`，于是再也不会把它误用。

最后一个要消灭的敌人是函数指针。

思考这样一个函数指针类型 `fn() -> &'a str`。该类型的函数实例被调用时，会返回具有某个生命周期 `'a` 的引用，因此可以用 `fn() -> &'static str` 类型的函数实例进行替换。毕竟，如果期望返回父类型 `&'a str`，实际返回子类型 `&'static str` 是安全的，所以函数指针 `fn(T) -> U` 对 `U` 应该协变。

同样的逻辑对函数参数并不适用，`fn(&'a str)` 的函数实例可以接收具有 `'a` 或更长生命周期的引用，而 `fn(&'static str)` 的函数实例只能接收 `'static` 生命周期的引用。显然可以用前者去替换后者，却不能用后者替换前者，所以函数指针 `fn(T) -> U` 对 `T` 应该逆变。

注意：Rust 语言中唯一的逆变是函数的参数，这解释了为何在实践中逆变并不常见。要触发逆变，需要使用函数指针，这些指针接收具有..特定生命周期..的引用，而非“..任意生命周期..” —— 后者涉及高阶的生命周期机制，独立于上述规则。

至此，我们已经讨论了标准库提供的类型，结构体、枚举和联合体类型的型变性取决于其字段的型变性。如果一个泛型参数被用于具有不同型变性的字段，那么该参数只能是不变的。例如，以下结构体对于 `'a` 和 `T` 是协变的，而对于 `'b`、`'c` 和 `U` 则是不变的：

```Rust
use std::cell::UnsafeCell;
struct Variance<'a, 'b, 'c, T, U: 'a> {
    x: &'a U,                // 对 'a 和 U 协变，但之后又使用了 U
    y: *const T,             // 对 T 协变
    z: UnsafeCell<&'b f64>,  // 对 'b 不变
    w: *mut U,               // 对 U 不变，使得整个结构体对 U 不变
    f: fn(&'c ()) -> &'c (), // 同时协变和逆变，使得整个结构体对 'c 不变
}
```

## `T: 'a` 约束

Rust 还可以用生命周期约束泛型类型，对应语法为 `T: 'a`。语义要求类型 `T` 在 `'a` 范围内保持有效，这和 `&'a T` 的语义类似 —— 引用 `&T` 对 `'a` 有效。

什么样的 `T` 对 `'a` 有效？如果类型 `T` 包含引用，那么这些引用的生命周期必须 outlive `'a`，以保证在 `'a` 内不会出现悬垂引用；如果类型 `T` 不含引用（如 `i32` `Box<i32>` `String`），则自动满足约束 —— 使用它们永远不必担心悬垂引用。特别的，`T: 'static` 要求 `T` 不能包含任何非 `'static` 引用。

按上述规则，所有 `&'a T` 类型都满足 `&'a T: 'a`，同时 `&'a T` 隐含了 `T: 'a` 约束：如果 `T` 不能保证对 `'a` 有效，那么其引用也不能保证对 `'a` 有效。例如，若有一个指向引用的引用 `&'a &'b T`，我们会得到：`'b: 'a`；反过来说，编译器不允许构造一个 `&'static Ref<'a, T>`。

`T: 'a` 约束还可用于抽象返回类型 `impl Trait`，考虑下例代码：

```Rust
fn say_some<'a>(name: String) -> impl Fn(&'a str) {
    move |text| println!("{name} syas: {text}")
}

fn main() {
    // 让我们称 phi 捕获的生命周期为 'f
    let phi: impl Fn(&str) = say_some("Blackbird".into()); // L1
    phi(&'x String::from("hello")); // L2
    phi(&'y String::from("world")); // L3
    // Drop::drop(phi); L4
}
```

若不显式指明 `use<..>` 块，抽象返回类型会隐式捕获当前范围的的泛型参数：编译器自动为 `impl Fn(&'a str)` 类型添加 `use<'a>`，以捕获生命周期参数 `'a`。根据变量 `phi` 的活性，其捕获的生命周期 `'f` 应包含 `L2 L3 L4` 节点，导致对 `"hello"` 和 `"world"` 的借用持续到作用域外，因此编译失败。

一个解决方案是为返回类型添加约束：`impl Fn(&'a str) + 'static`。静态生命周期约束确保 `phi` 的类型不包含 `'f`（即使它被自动捕获），那么 `'f` `'x` `'y` 只存在于子类型化约束：`('x: 'f) @ L2` `('y: 'f) @ L3`，约束自动满足。

更优雅的方法是删掉生命周期 `'a`：`fn say_some(name: String) -> impl Fn(&str)`，如此 `Fn(&str)` 会解糖为高阶特型约束 `for<'a> Fn(&'a str)`，从而使 `phi` 能接收任意生命周期的引用。

## 高阶特型约束

高阶特型约束(HRTBs)的全名是 _Higher-Ranked Trait Bounds_，语法形如 `for<'a> Trait<'a>`，语义是“对任意生命周期 `'a` 实现了 `Trait<'a>`”。`for<'a>` 的意义在于引入一个独立的、上下文无关的高阶生命周期，从而与当前环境解耦。让我们试着描述两个 `say_some` 的语义：

1. `fn say_some<'a>(name: String) -> impl Fn(&'a str)`：输入任意生命周期 `'a` 和任意实例 `name: String`，返回一个实例 `phi = say_some::<'a>(name)`，其类型只对输入的这个 `'a` 实现了 `Fn(&'a str)`，所以 `phi` 只能接收特定的 `&'a str`。

2. `fn say_some(name: String) -> impl for<'a> Fn(&'a str)`：输入任意实例 `name: String`，返回一个实例 `phi = say_some(name)`，其类型对任意生命周期 `'a` 都实现了 `Fn(&'a str)`，所以 `phi` 能接收不同的 `&'a str`。

以上从语义角度解释了 HRTBs。别忘了，所有的泛型最终都会单态化为一个确定的“值”。`for<'a>` 的实质，就是将 `'a` 的单态化从 `say_some` 的调用推迟到 `phi` 的调用！

> 注意：`Fn(A) -> B` 实际是 `Fn<(A,), B>` 的语法糖，考虑到 `Fn*` 特型的格式将来可能改变，Rust 要求使用语法糖形式。

`for<'a>` 还可用于函数指针与特型对象。高阶类型适用另一种子类型规则，它们是那些通过替换其高阶生命周期所得到的类型的子类型：

```Rust
// 函数指针：高阶生命周期 'a 被替换为 'static
let subtype: &(for<'a> fn(&'a i32) -> &'a i32) = &((|x| x) as fn(&_) -> &_);
let supertype: &(fn(&'static i32) -> &'static i32) = subtype;

// 特型对象同理
let subtype: &(dyn for<'a> Fn(&'a i32) -> &'a i32) = &|x| x;
let supertype: &(dyn Fn(&'static i32) -> &'static i32) = subtype;

// 也可以用一个高阶生命周期替换另一个
let subtype: &(for<'a, 'b> fn(&'a i32, &'b i32))= &((|x, y| {}) as fn(&_, &_));
let supertype: &for<'c> fn(&'c i32, &'c i32) = subtype;
```

紧随而至的问题是，哪些类型能满足高阶特型约束 `for<'a> Trait<'a>`？我们以函数类型和 `Fn*` 特型为例，来说明这个问题：

Rust 中，每个函数定义都对应一个实现了 `Fn*` 特型的零大小类型(ZST)，即函数项类型(Function item type)。考虑一个带有泛型 `<'a, T>` 的函数：

```Rust
fn foo<'a, T: Sized>(a: &'a T) -> &'a T {
    /* snip */
}
```

`foo` 对应的函数项类型及其 `Fn` 实现大致如下（省略了 `FnMut`/`FnOnce` 特征）：

```Rust
struct FooFnItem<T: Sized>(PhantomData<for<'a> fn(&'a T) -> &'a T>);

impl<'a, T: Sized> Fn<(&'a T,)> for FooFnItem<T> {
    type Output = &'a T;
    fn call(&self, ...) -> ... { ... }
}
```

可以看到，函数项类型 `FooFnItem<T>` 上只定义了泛型参数 `T`。函数实例化会推断泛型 `T` 的值：

```Rust
let phi = foo; // T 被推断为 String
phi(&String::new());
```

实例 `phi` 的类型是 `FooFnItem<String>`。根据 `impl` 代码，`FooFnItem<String>` 对任意的 `'a` 都实现了特型 `Fn<(&'a String,)>`，所以 `phi` 可以传入 `want_hrtb`：

```Rust
fn want_hrtb<F>(f: F)
where
    F: for<'r> Fn(&'r String) -> &'r String,
{
    /* snip */
}
```

实例调用 `phi(&String::new())` 被解糖为 `phi.call(&String::new())`，每次调用编译器都会确定一个独立的 `'a`。对函数 `foo` 而言，`T` 和 `'a` 单态化的时间不同，前者发生于 `foo` 的实例化，称为早绑定(Early bound)，后者发生于 `foo` 的调用，称为晚绑定(Late bound)。显然，只有晚绑定的生命周期才能转换为高阶生命周期。

<!-- 通过函数名调用函数时，`foo(&"".into())` -->

早绑定的泛型参数在实例化时可以使用 [turbofish](https://turbo.fish/) 语法指定，晚绑定则不行，因为函数项类型没有晚绑定参数的“位置”：

```Rust
let phi = foo::<String>;
let phi = foo::<'static, String>; // 报错
```

编译器根据函数定义生成函数项类型时，按照以下规则处理泛型参数：

1. 所有泛型类型参数 `T` 都是早绑定
2. 泛型生命周期参数 `'a` 是晚绑定，除非：
  - 出现在 `where` 子句中：`fn foo<'a: 'a>() {}` 或 `fn bar<'a, T: 'a>() {}`
  - 只用于返回类型：`fn foo<'a>() -> &'a String {}`
  - 函数定义位于 `impl` 块中，且生命周期由 `impl<'a>` 声明

更多解释见[Rust Compiler Dev Guide](https://rustc-dev-guide.rust-lang.org/early_late_parameters.html?highlight=early#requirements-for-a-parameter-to-be-late-bound)。

早晚绑定的概念不局限于函数项类型，对于一般的类型 `AnyItem`：

```Rust
// 'late 是晚绑定，满足 AnyItem : for<'late> Trait<'late>
impl<'late> Trait<&'late Foo> for AnyItem { ... }

// 'early 是早绑定，满足 AnyItem<'early> : Trait<'early>
impl<'early> Trait<&'early Foo> for AnyItem<'early> { ... }

// 'assoc 是早绑定，满足 AnyItem<'early> : Trait<'assoc>
impl<'assoc> Trait<'assoc> for AnyItem<'early> 
where 'assoc: 'early
{ ... }
```

## 生命周期的新进展 Polonius

<!-- ## NLL 的局限

上文提到，Rust 借用检查比理想情况更严格。

因而编译器推断 `f` 的类型是 `for<'a> fn(&'a String) -> &'a String {foo::<String>}`，`{foo::<String>}` 表明这是一个。 -->