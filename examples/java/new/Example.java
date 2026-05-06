public class Example {
    // Breaking: changed parameter types from int to float
    public static float add(float a, float b) {
        return a + b;
    }

    public static void greet(String name) {
        System.out.println("Hello, " + name + "!");
    }

    public static void main(String[] args) {
        float result = add(5.0f, 3.0f);
        greet("World");
    }
}
