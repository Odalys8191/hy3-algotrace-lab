#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int t; cin >> t;
    while (t--) {
        int n; cin >> n;
        vector<long long> a(n), sums(1 << n);
        for (auto &x : a) cin >> x;
        unordered_set<long long> seen;
        seen.reserve(2 << n);
        // The empty subset is omitted.
        bool possible = false;
        for (int mask = 1; mask < (1 << n); ++mask) {
            int bit = __builtin_ctz((unsigned)mask);
            sums[mask] = sums[mask ^ (1 << bit)] + a[bit];
            if (!seen.insert(sums[mask]).second) possible = true;
        }
        cout << (possible ? "YES" : "NO") << '\n';
    }
}
