#include <iostream>
int main() { int n, x, answer = 0; std::cin >> n; while (n-- && std::cin >> x) answer += x > 0; std::cout << answer << '\n'; }
