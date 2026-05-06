# Breaking: changed method signature (different semantics)
def add(*args)
  args.sum
end

def greet(name)
  puts "Hello, #{name}!"
end

def main
  result = add(5, 3)
  greet("World")
end

main()
