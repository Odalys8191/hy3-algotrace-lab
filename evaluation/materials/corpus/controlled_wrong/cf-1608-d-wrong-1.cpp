#include <bits/stdc++.h>
using namespace std;
using ll = long long;
const ll MOD = 998244353;
ll power(ll a, ll e) {
    ll r = 1;
    while (e) {
        if (e & 1) r = r * a % MOD;
        a = a * a % MOD; e >>= 1;
    }
    return r;
}
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int n; cin >> n;
    int blacks = 0, unknown = 0;
    ll mixed = 1;
    bool all_bw = true, all_wb = true;
    for (int i = 0; i < n; ++i) {
        string s; cin >> s;
        for (char c : s) { blacks += (c == 'B'); unknown += (c == '?'); }
        bool bw = (s[0] != 'W' && s[1] != 'B');
        bool wb = (s[0] != 'B' && s[1] != 'W');
        mixed = mixed * (int(bw) + int(wb)) % MOD;
        all_bw = all_bw && bw;
        all_wb = all_wb && wb;
    }
    vector<ll> fact(unknown + 1, 1);
    for (int i = 1; i <= unknown; ++i) fact[i] = fact[i-1] * i % MOD;
    int need = n - blacks;
    ll balanced = 0;
    if (0 <= need && need <= unknown)
        balanced = fact[unknown] * power(fact[need], MOD-2) % MOD * power(fact[unknown-need], MOD-2) % MOD;
    ll answer = (balanced + int(all_bw) + int(all_wb)) % MOD;
    if (answer < 0) answer += MOD;
    cout << answer << '\n';
}
