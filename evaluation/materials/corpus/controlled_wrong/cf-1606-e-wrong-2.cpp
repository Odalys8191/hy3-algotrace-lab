#include <bits/stdc++.h>
using namespace std;
using ll = long long;
const int MOD = 998244353;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int n, x; cin >> n >> x;
    int lim = max(n, x);
    vector<vector<int>> choose(n + 1, vector<int>(n + 1));
    vector<vector<int>> pw(lim + 1, vector<int>(n + 1, 1));
    for (int b = 0; b <= lim; ++b)
        for (int e = 1; e <= n; ++e) pw[b][e] = (ll)pw[b][e-1] * b % MOD;
    choose[0][0] = 1;
    for (int i = 1; i <= n; ++i) {
        choose[i][0] = choose[i][i] = 1;
        for (int j = 1; j < i; ++j)
            choose[i][j] = (choose[i-1][j-1] + choose[i-1][j]) % MOD;
    }
    vector<vector<int>> dp(n + 1, vector<int>(x + 1));
    for (int h = 0; h <= x; ++h) dp[0][h] = 1;
    for (int h = 1; h <= x; ++h) {
        for (int alive = 2; alive <= n; ++alive) {
            if (h <= alive - 1) {
                dp[alive][h] = pw[h][alive];
                continue;
            }
            int remaining = h - alive;
            ll ways = 0;
            for (int survive = 0; survive <= alive; ++survive) {
                ll term = (ll)choose[alive][survive] * pw[alive-1][alive-survive] % MOD;
                ways = (ways + term * dp[survive][remaining]) % MOD;
            }
            dp[alive][h] = ways;
        }
    }
    cout << dp[n][x] << '\n';
}
