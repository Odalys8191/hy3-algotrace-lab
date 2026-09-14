#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int n, m; cin >> n >> m;
    vector<int> higher(n + 1);
    int answer = n;
    auto add = [&](int u, int v) {
        if (u > v) swap(u, v);
        ++higher[u]; --answer;
    };
    auto remove_edge = [&](int u, int v) {
        if (u > v) swap(u, v);
        if (--higher[u] == 0) ++answer;
    };
    for (int i = 0; i < m; ++i) {
        int u, v; cin >> u >> v; add(u, v);
    }
    int q; cin >> q;
    while (q--) {
        int type; cin >> type;
        if (type == 3) cout << answer << '\n';
        else {
            int u, v; cin >> u >> v;
            if (type == 1) add(u, v);
            else remove_edge(u, v);
        }
    }
}
