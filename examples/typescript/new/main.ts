// Breaking: changed parameter types from number to string (different semantics)
export function add(a: string, b: string): string {
    return a + b;
}

export function greet(name: string): void {
    console.log(`Hello, ${name}!`);
}

function main(): void {
    const result = add("5", "3");
    greet("World");
}

main();
