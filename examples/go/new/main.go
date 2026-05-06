package main

import "fmt"

// Breaking: changed return type from int to float64
func Add(a float64, b float64) float64 {
    return a + b
}

func Greet(name string) {
    fmt.Printf("Hello, %s!\n", name);
}

func main() {
    result := Add(5.0, 3.0)
    Greet("World")
}
