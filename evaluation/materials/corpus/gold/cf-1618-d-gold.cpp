#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int t; cin >> t;
    while (t--) {
        int n, k; cin >> n >> k;
        vector<int> a(n);
        for (int &x : a) cin >> x;
        sort(a.begin(), a.end());
        long long answer = 0;
        int keep = n - 2 * k;
        for (int i = 0; i < keep; ++i) answer += a[i];
        for (int i = 0; i < k; ++i)
            answer += (a[keep + i] == a[keep + k + i]);
        cout << answer << '\n';
    }
}
