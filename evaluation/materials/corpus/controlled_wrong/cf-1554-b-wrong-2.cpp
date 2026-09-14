#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int t; cin >> t;
    while (t--) {
        int n, k; cin >> n >> k;
        vector<int> a(n + 1);
        for (int i = 1; i <= n; ++i) cin >> a[i];
        long long answer = 0;
        int first = max(1, n - 2 * k);
        for (int i = first; i <= n; ++i)
            for (int j = i + 1; j <= n; ++j)
                answer = max(answer, 1LL * i * j - 1LL * k * (a[i] | a[j]));
        cout << answer << '\n';
    }
}
