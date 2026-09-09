// AI-authored project smoke reference; not an official or Judge-verified solution.
#include <iostream>
#include <vector>

constexpr long long damage(const long long* attacks, int n, long long k) {
    long long total = k;
    for (int i = 1; i < n; ++i) {
        const long long gap = attacks[i] - attacks[i - 1];
        total += k < gap ? k : gap;
    }
    return total;
}

constexpr long long minimum_strength(const long long* attacks, int n, long long health) {
    long long low = 1;
    long long high = health;
    while (low < high) {
        const long long middle = low + (high - low) / 2;
        if (damage(attacks, n, middle) >= health) {
            high = middle;
        } else {
            low = middle + 1;
        }
    }
    return low;
}

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    int test_cases;
    std::cin >> test_cases;
    while (test_cases--) {
        int n;
        long long health;
        std::cin >> n >> health;
        std::vector<long long> attacks(n);
        for (long long& time : attacks) {
            std::cin >> time;
        }
        std::cout << minimum_strength(attacks.data(), n, health) << '\n';
    }
    return 0;
}
