#include <bits/stdc++.h>
using namespace std;
using ll = long long;
const ll MOD = 1000000007;
ll power(ll a, int e) {
    ll r = 1;
    while (e) {
        if (e & 1) r = r * a % MOD;
        a = a * a % MOD;
        e >>= 1;
    }
    return r;
}
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int t; cin >> t;
    while (t--) {
        int n, k; cin >> n >> k;
        ll half = power(2, n - 1), all = half * 2 % MOD;
        ll equal_choices = (half + (n % 2 ? 1 : MOD - 1)) % MOD;
        ll greater_choices = (n % 2 == 0 ? 1 : 0);
        ll equal = 1, greater = 0;
        for (int bit = 0; bit < k; ++bit) {
            greater = (greater * all + equal * greater_choices) % MOD;
            equal = equal * equal_choices % MOD;
        }
        cout << (equal + greater) % MOD << '\n';
    }
}
