#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int t; cin >> t;
    while (t--) {
        long long n, m, k; cin >> n >> m >> k;
        long long complete = n * (n - 1) / 2;
        bool possible = false;
        if (m >= n - 1 && m <= complete) {
            long long diameter = (n == 1 ? 0 : (m == complete ? 1 : 2));
            possible = diameter <= k - 1;
        }
        cout << (possible ? "YES" : "NO") << '\n';
    }
}
