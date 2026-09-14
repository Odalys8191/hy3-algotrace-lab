#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int t; cin >> t;
    while (t--) {
        int n; cin >> n;
        vector<int> a(n), b(n), by_a(n), by_b(n);
        for (int &x : a) cin >> x;
        for (int &x : b) cin >> x;
        iota(by_a.begin(), by_a.end(), 0);
        iota(by_b.begin(), by_b.end(), 0);
        sort(by_a.begin(), by_a.end(), [&](int u, int v) { return a[u] < a[v]; });
        sort(by_b.begin(), by_b.end(), [&](int u, int v) { return b[u] < b[v]; });
        vector<vector<int>> rev(n);
        for (int i = 1; i < n; ++i) {
            rev[by_a[i - 1]].push_back(by_a[i]);
            rev[by_b[i - 1]].push_back(by_b[i]);
        }
        string answer(n, '0');
        queue<int> todo;
        todo.push(by_a.back()); answer[by_a.back()] = '1';
        while (!todo.empty()) {
            int u = todo.front(); todo.pop();
            for (int v : rev[u]) if (answer[v] == '0') {
                answer[v] = '1'; todo.push(v);
            }
        }
        cout << answer << '\n';
    }
}
