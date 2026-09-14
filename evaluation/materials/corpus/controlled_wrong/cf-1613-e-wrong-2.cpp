#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int t; cin >> t;
    const int dr[4] = {-1, 1, 0, 0};
    const int dc[4] = {0, 0, -1, 1};
    while (t--) {
        int n, m; cin >> n >> m;
        vector<string> grid(n);
        for (auto &row : grid) cin >> row;
        vector<int> degree(n * m);
        queue<int> todo;
        for (int r = 0; r < n; ++r) for (int c = 0; c < m; ++c) {
            if (grid[r][c] == '#') continue;
            int u = r * m + c;
            if (grid[r][c] == 'L') todo.push(u);
            for (int d = 0; d < 4; ++d) {
                int nr = r + dr[d], nc = c + dc[d];
                if (0 <= nr && nr < n && 0 <= nc && nc < m && grid[nr][nc] != '#') ++degree[u];
            }
        }
        while (!todo.empty()) {
            int u = todo.front(); todo.pop();
            int r = u / m, c = u % m;
            for (int d = 0; d < 4; ++d) {
                int nr = r + dr[d], nc = c + dc[d];
                if (nr < 0 || nr >= n || nc < 0 || nc >= m || grid[nr][nc] != '.') continue;
                int v = nr * m + nc;
                if (degree[v] <= 1) {
                    grid[nr][nc] = '+';
                    todo.push(v);
                }
            }
        }
        for (auto &row : grid) cout << row << '\n';
    }
}
