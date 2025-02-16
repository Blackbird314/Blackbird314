+++
title = "Rust 语法辨析：借用与重借用"
date = "2024-07-07T16:39:09+08:00"
tags = ["Rust"]
slug = "rust-reference"
+++

## 借用

和 C/C++ 一样，Rust 有裸指针(Pointer)类型和引用(Reference)类型，分别是共享引用（不可变引用） `&T` 和可变引用 `&mut T`，常量裸指针（不可变指针） `*const T` 和可变裸指针 `*T`，他们的值都是 `T` 类型对象的内存地址，都可以通过解引用操作访问内存对象。

区别在于，裸指针是不安全的操作，只能在 `unsafe` 块中使用；引用则是被编译器加了限制的指针，遵循借用规则(Borrowing Rules)并由编译器检查，以保证安全。

为了方便，Rust 引用的作用域比普通变量更短：普通变量的作用域从初始化持续到最近的花括号 `}`；引用的作用域从借用开始，一直持续到它最后一次使用的地方。这种优化行为被称为非词法作用域生命周期(Non-Lexical Lifetimes, NLL)。

创建一个引用的行为称为借用(Borrowing)，代表着引用会借用（而非获得）原变量对内存对象的所有权。当你不想转移所有权时，可以通过借用访问内存对象，例如：

```Rust
fn main() {
    let s1 = String::from("hello"); // s1 本质是一个指向堆内存的指针

    let len = calculate_length(&s1); // 发生了不可变借用

    println!("The length of '{}' is {}.", s1, len);
}

fn calculate_length(s: &String) -> usize { // s 是指向 s1 的引用
    s.len()
}
```

传入 `calculate_length()` 的是 `s1` 的共享引用，参数 `s` 会借用 `s1` 的所有权，如图所示：

![2024-05-24-15-42-23.png](/images/2024-05-24-15-42-23.png)

Rust 存在三条基本的借用规则：

- 共享引用(`&T`)有效期间，只能由被引用对象借出共享引用，只能以只读的方式访问被引用对象
- 可变引用(`&mut T`)有效期间，无法由被引用对象借出任何引用，无法访问被引用对象
- 引用必须总是有效的，即引用的生命周期不能超过原变量的生命周期。所以当存在借用时，原变量不能转移所有权，但可以 Copy 或 Clone

换言之，在同一时刻，要么只存在一个可变引用(`&mut T`)，要么存在任意数量的共享引用(`&T`)。正因如此，可变引用 `&mut T` 没有实现 `Copy`，否则很容易违反借用规则。相反，共享引用是可 Copy 的，即把共享引用赋值给另一个共享引用后，可以继续使用。

为什么会有这样的规则呢？因为 Rust 希望在同一时刻，..一份资源只能被至多一个变量名读写，或者被多个变量名读取..。由此，下面这段代码会报错：

```Rust
fn main() {
    let mut x = 0;
    let y = &mut x; // y 可变借用于 x
    if x == 0 { // 报错：不能通过原变量 x 读取或写入内存对象，因为此时存在 x 的可变引用 y
        *y += 1; // y 的作用域到此结束
        println!("{}", x); // x 可以正常读取
    }
}
```

## 解引用

解引用操作 `*r` 会得到一个被称为影子变量的东西，可以理解为没有所有权的变量别名。它可以用来对内存对象进行读写，但不能通过它转移所有权，这会影响本体对于内存对象的掌控（可以 Copy 或 Clone）：

```Rust
struct MyType<T> {
    val: T
}

fn main() {
    let num1 = 1;
    let num1_ref = &num1;
    let num2 = *num1_ref; // i32 实现了 Copy，因此影子变量 *num1_ref 会进行 Copy 操作，这不会影响本体的所有权
    
    let x = MyType{val: 1};
    let y = &x;
    let z = *y; // MyType<i32> 没有实现 Copy，不能通过影子变量 *y 移动所有权，编译报错
}
```

## 引用类型的所有权

Rust 中所有的值都有所有权，引用类型的值也不例外。引用不拥有指向对象的所有权，但引用变量拥有自身地址值的所有权：

```Rust
fn main() {
    let mut s = String::from("value");
    let r = &mut s; // r 是 s 的可变引用
    let _r1 = r; // move 而非 copy
    let _r2 = r; // 报错：use of moved value: `r`
}
```

我们知道，共享引用实现了 `Copy`，自然也实现了 `Clone`，而下面的结构体 `Person` 没有实现 `Clone`，因此 `b.clone()` 只能复制引用 `b`，不能复制引用指向的内存对象。虽然这能通过编译，但 clippy 不建议我们这样做，因为它的行为相当于 `Copy` 操作，很可能不是我们希望的克隆效果。

```Rust
struct Person;

fn main() {
    let a = Person;
    let b = &a;
    // 警告：the type `Person` does not implement `Clone`, so calling `clone` on `&Person` copies the reference, which does not do anything and can be removed
    let _c: &Person = b.clone();
}
```

但如果为结构体 `Person` 实现 `Clone`，再去 `clone()` 引用类型，将没有错误提示：

```Rust
#[derive(Clone)]
struct Person;

fn main() {
    let a = Person;
    let b = &a;
    let _c: Person = b.clone(); // 此时 _c 的类型是 Person，而不是 &Person
}
```

前后两个示例的区别，仅在于引用所指向的类型 `Person` 有没有实现 `Clone`。原因在于，方法调用时会先查找与调用者类型匹配的方法，查找过程具有优先级，找到即停。由于 `.` 操作可以自动引用/解引用，如果引用/解引用前后的两种类型都实现了同一方法(如 `clone()`)，Rust 编译器将按照查找顺序来决定调用哪个类型上的方法。[^1]

如果 `b` 是没有实现 `Copy` 和 `Clone` 的可变引用，`b.clone()` 只能得到 `Person` 类型（前提是 `Person` 实现了 `Clone`）。

## 小结

这张图展示了变量、类型、内存对象、值，引用、解引用和裸指针的概念：

![2024-05-24-17-17-25.png](/images/2024-05-24-17-17-25.png)

## 重借用

上文提到，借用检查不允许对一个实例的多个可变引用，也不能同时存在共享和可变引用。但对解引用得到的影子变量进行借用（重借用）却是可行的：

```Rust
let mut s = String::from("ABC");
let r1 = &mut s;
{
    let r2 = &mut *r1; // 重借用
    r2.push('2');
    println!("{}", r2); // r2 的作用域到此结束
}
println!("{}", r1); // r1 的作用域到此结束
```

这段代码的大括号内，同时存在 `r1` `r2` 两个指向同一变量 `s` 的可变引用，但编译器不会报错。这是因为编译器看到 `*r1` 的时候，通常很难确定解引用得到的对象是什么，所以借用检查不会把 `*r1` 跟 `s` 当成同一个对象，自然不会报错。

重借用遵循的规则与借用规则类似：

- 不可变重借用的有效期间，原始引用只能继续重借用出共享引用，只能以只读的方式访问原始引用
- 可变重借用的有效期间，无法由被原引用重借用出任何引用，无法访问原始引用

可变引用的重借用实际上是在这个可变引用的生命周期内分化出多个不相交的、较小范围（生命周期）的可变引用。范围不相交意味着遵守了引用的规则："At any given time, you can have either one mutable reference or any number of immutable references"。

```Rust
struct A(i32,i32);
impl A {
    fn foo(&mut self) {
        let a = &self.0; // 相当于 let a = &(*self).0;
        self.bar(); // 相当于 bar(&mut *self);
        a;
    }
    fn bar(&mut self) {}
}
```

上述代码会报错，`self.0` 是 `self` 的不可变重借用，而 `self.bar()` 是对 `self` 的可变重借用，包括了第一个元素这条路径，所以编译失败。假如把 `bar()` 签名改成 `fn bar(&self)` 则编译成功。

### 隐式重借用

```Rust
let mut s = String::from("ABC");
let r1 = &mut s;
{
    let r2 = &mut *r1;

    let l = r1.len(); // 错误 Cannot borrow `*r1` as immutable because it is also borrowed as mutable
    println!("{}", l);
    r2.push('2');
    r1.push('3'); // 错误 Cannot borrow `*r1` as mutable more than once at a time
    println!("{:?}", r1); // 错误 Cannot borrow `r1` as immutable because it is also borrowed as mutable
    println!("{}", r2);
}
println!("{}", r1);
```

你可能会好奇，明明传入方法的是引用类型，为什么报错信息中会显示 `*r1`？这是因为自动发生了隐式重借用，`r1.len()` 实际上是 `String::len(&*r1)`，同理 `r1.push('3')` 实际上是 `String::push(&mut *r1, '3')`。

隐式重借用并非多此一举，`len()` 和 `push()` 的方法签名分别是 `pub fn len(&self) -> usize` 和 `pub fn push(&mut self, ch: char)`。没有隐式重借用，可变引用 `r1` 将无法直接调用 `len()`，而 `r1.push('3')` 调用会转移可变引用 `r1` 的所有权，导致 `r1` 之后无法使用。

实际上，隐式重借用几乎无处不在：

```Rust
let mut s = String::from("ABC");
let r1 = &mut s;
// 不标注 r2 的类型，会 Move 而非隐式重借用，之后 r1 失效
let r2 = r1;
// 手动标注 r2 的类型，会进行隐式重借用，函数传参同理
let r3: &mut String = r2; // 相当于 let r3: &mut String = &mut *r2;
println!("{:?}", r3);
println!("{:?}", r2); // 打印 r3 r2 的顺序不能颠倒
```

对共享引用 `&T`，可以认为发生了重借用, 也可以认为直接发生 `Copy`，因为效果完全一样。

### 手动重借用

下面这两种情况[^2]，`from()` 函数不会自动重借用：

```Rust
struct X;

impl From<&mut i32> for X {
    fn from(i: &mut i32) -> Self {
        X
    }
}

fn from_auto_reborrow<'a, F, T: From<&'a mut F>>(f: &'a mut F) -> T {
    T::from(f)
}

fn from<F, T: From<F>>(f: F) -> T {
    T::from(f)
}

fn main() {
    let mut i = 4;
    let r = &mut i;

    let _x: X = from_auto_reborrow(r); // 隐式重借用

    let _x: X = from(&mut *r); // 显式重借用以避免 Move r
    let _x: X = from(r); // 不会进行隐式重借用, 导致 Move r
    let _x: X = from(r); // 编译失败
}
```

```Rust
struct I(i32);
struct X;

impl From<&mut I> for X {
    fn from(p: &mut I) -> X {
        p.0 = 1;
        X
    }
}

// 必须引入这个中间函数
fn x_from(p: &mut I) -> X {
    X::from(p)
}

// value used here after move
fn from_twice_fail(p: &mut I) {
    let _x1 = X::from(p); // 此处不会自动重借用, 导致 Move p
    let _x2 = X::from(p); // 编译失败
}

fn from_twice(p: &mut I) {
    let _x1 = x_from(p); // 隐式重借用
    let _x2 = x_from(p); // 编译通过
}
```

关于上述现象，有这么几个猜想：

1. 重借用是一种 type coercion，结合 type coercion 的文档，type coercion 可能只能在源类型和目的类型都知道的情况下进行
2. rustc 的类型推断进程很可能没有 100% 完成，所以一部分值的类型是不是引用仍然是不知道的，于是此时重借用就不会发生
3. 对参数的分析很可能是从第一个参数到最后一个参数依次进行的，如果对前面参数的分析推断到了更多的类型信息，那么对后面参数的分析就会利用前面得到的类型信息

```Rust
struct A;
struct B;

trait Hey<T> {
    fn hey(p: T, q: T);
}

impl Hey<u32> for B {
    fn hey(p: u32, q: u32) { todo!() }
}

impl Hey<&mut A> for B {
    fn hey(p: &mut A, q: &mut A) { todo!() }
}

fn hey_hey(p: &mut A, q: &mut A) {
    // <B as Hey<_>> 中的 _ 类型有两种可能，需要被推断：
    <B as Hey<_>>::hey(p, q);
    // 编译器抱怨 p 已被移走，但是 q 却依然可以使用：
    <B as Hey<_>>::hey(p, q);
}
```

---

[^1]: 参考：<https://rustc-dev-guide.rust-lang.org/method-lookup.html?highlight=lookup#method-lookup>

[^2]: 参考：<https://rustcc.cn/article?id=28fedcbc-d0c9-41e1-8d95-de73a578a078>
