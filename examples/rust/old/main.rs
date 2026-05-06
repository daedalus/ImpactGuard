pub fn add(a: i32, b: i32) -> i32 {
    a + b
}

pub fn greet(name: &str) {
    println!("Hello, {}!", name);
}

fn main() {
    let result = add(5, 3);
    greet("World");
}
