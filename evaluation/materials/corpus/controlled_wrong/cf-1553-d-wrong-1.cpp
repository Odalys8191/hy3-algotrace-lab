#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int q; cin >> q;
    while (q--) {
        string s, t; cin >> s >> t;
        int i = (int)s.size() - 1, j = (int)t.size() - 1;
        while (i >= 0 && j >= 0) {
            if (s[i] == t[j]) { --i; --j; }
            else i -= 1;
        }
        cout << (j < 0 ? "YES" : "NO") << '\n';
    }
}
