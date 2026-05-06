// Breaking: changed parameter types from i32 to f64
pub fn add(a: f64, b: f64) -> f64 {
    a + b
}

pub fn greet(name: &str) {
    println!("Hello, {}!", name);
}

fn main() {
    let result = add(5.0, 3.0);
    greet("World");
}
