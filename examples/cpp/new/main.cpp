#include <iostream>
#include <string>

// Breaking: changed return type from int to double
double add(int a, int b) {
    return static_cast<double>(a + b);
}

void greet(const std::string& name) {
    std::cout << "Hello, " << name << "!\n";
}

int main() {
    int result = static_cast<int>(add(5, 3));
    greet("World");
    return 0;
}
