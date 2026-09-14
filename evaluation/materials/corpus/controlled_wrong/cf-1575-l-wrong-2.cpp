#include <bits/stdc++.h>
using namespace std;
struct Fenwick {
    int n; vector<int> bit;
    explicit Fenwick(int n): n(n), bit(n + 1) {}
    int query(int p) {
        int r = 0;
        for (; p > 0; p -= p & -p) r = max(r, bit[p]);
        return r;
    }
    void update(int p, int v) {
        for (; p <= n; p += p & -p) bit[p] = max(bit[p], v);
    }
};
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int n; cin >> n;
    vector<pair<int,int>> points;
    for (int i = 1; i <= n; ++i) {
        int a; cin >> a;
        if (a < i) points.push_back({a, i - a});
    }
    sort(points.begin(), points.end());
    Fenwick fw(n + 1);
    int answer = 0;
    for (int l = 0; l < (int)points.size(); ) {
        int r = l;
        while (r < (int)points.size() && points[r].first == points[l].first) ++r;
        vector<pair<int,int>> pending;
        for (int j = l; j < r; ++j) {
            int d = points[j].second;
            int best = fw.query(d + 1) + 1;
            pending.push_back({d + 1, best});
            answer = max(answer, best);
        }
        for (auto [p, value] : pending) fw.update(p, value);
        l = r;
    }
    cout << answer << '\n';
}
