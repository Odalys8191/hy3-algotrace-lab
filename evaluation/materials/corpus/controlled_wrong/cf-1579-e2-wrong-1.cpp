#include <bits/stdc++.h>
using namespace std;
struct Fenwick {
    int n; vector<int> bit;
    explicit Fenwick(int n): n(n), bit(n + 1) {}
    int sum(int p) {
        int r = 0;
        for (; p > 0; p -= p & -p) r += bit[p];
        return r;
    }
    void add(int p) {
        for (; p <= n; p += p & -p) ++bit[p];
    }
};
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int t; cin >> t;
    while (t--) {
        int n; cin >> n;
        vector<int> a(n);
        for (int &x : a) cin >> x;
        vector<int> values = a;
        sort(values.begin(), values.end());
        values.erase(unique(values.begin(), values.end()), values.end());
        Fenwick fw(values.size());
        long long answer = 0;
        for (int i = 0; i < n; ++i) {
            int rank = lower_bound(values.begin(), values.end(), a[i]) - values.begin() + 1;
            int smaller = fw.sum(rank);
            int larger = i - fw.sum(rank);
            answer += min(smaller, larger);
            fw.add(rank);
        }
        cout << answer << '\n';
    }
}
