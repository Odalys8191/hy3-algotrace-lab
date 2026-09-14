#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int t; cin >> t;
    while (t--) {
        string s; cin >> s;
        long long lane[2] = {0, 0};
        for (int i = 0; i < (int)s.size(); ++i)
            lane[i % 2] = lane[i % 2] + (s[i] - '0');
        cout << (lane[0] + 1) * (lane[1] + 1) - 2 << '\n';
    }
}
