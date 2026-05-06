#include <iostream>
#include <string>

int add(int a, int b) {
    return a + b;
}

void greet(const std::string& name) {
    std::cout << "Hello, " << name << "!\n";
}

int main() {
    int result = add(5, 3);
    greet("World");
    return 0;
}
