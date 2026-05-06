package main

import "fmt"

func Add(a int, b int) int {
    return a + b
}

func Greet(name string) {
    fmt.Printf("Hello, %s!\n", name)
}

func main() {
    result := Add(5, 3)
    Greet("World")
}
