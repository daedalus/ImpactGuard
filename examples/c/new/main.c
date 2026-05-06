#include <stdio.h>

// Breaking: changed return type from int to float
float add(int a, int b) {
    return a + b;
}

void greet(const char* name) {
    printf("Hello, %s!\n", name);
}

int main() {
    int result = add(5, 3);
    greet("World");
    return 0;
}
