#include <bits/stdc++.h>
using namespace std;
using ll = long long;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int n, m, q; cin >> n >> m >> q;
    int total = n + m;
    vector<pair<int,int>> items;
    items.reserve(total);
    for (int i = 0; i < n; ++i) { int x; cin >> x; items.push_back({x, 1}); }
    for (int i = 0; i < m; ++i) { int x; cin >> x; items.push_back({x, 0}); }
    vector<pair<int,int>> queries(q);
    for (int i = 0; i < q; ++i) { cin >> queries[i].first; queries[i].second = i; }
    sort(items.begin(), items.end());
    sort(queries.begin(), queries.end());
    vector<ll> prefix(total + 1), answer(q);
    vector<int> parent(total), size(total, 1), left(total), right(total), own(total);
    for (int i = 0; i < total; ++i) {
        prefix[i+1] = prefix[i] + items[i].first;
        parent[i] = left[i] = right[i] = i;
        own[i] = items[i].second;
    }
    auto find = [&](int x) {
        while (parent[x] != x) {
            parent[x] = parent[parent[x]];
            x = parent[x];
        }
        return x;
    };
    auto contribution = [&](int root) -> ll {
        return prefix[right[root] + 1] - prefix[right[root] + 1 - own[root]];
    };
    vector<pair<int,int>> edges;
    edges.reserve(total - 1);
    for (int i = 0; i + 1 < total; ++i)
        edges.push_back({items[i+1].first - items[i].first, i});
    sort(edges.begin(), edges.end());
    ll current = 0;
    for (int i = 0; i < total; ++i) current += contribution(i);
    int next_edge = 0;
    for (auto [k, index] : queries) {
        while (next_edge < (int)edges.size() && edges[next_edge].first < k) {
            int pos = edges[next_edge++].second;
            int u = find(pos), v = find(pos + 1);
            if (u == v) continue;
            current -= contribution(u) + contribution(v);
            if (size[u] < size[v]) swap(u, v);
            parent[v] = u;
            size[u] += size[v];
            left[u] = min(left[u], left[v]);
            right[u] = max(right[u], right[v]);
            own[u] += own[v];
            current += contribution(u);
        }
        answer[index] = current;
    }
    for (ll value : answer) cout << value << '\n';
}
