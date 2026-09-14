"""Independent project agent-authored references from sanitized public statements.

No third-party submissions or hidden test contents were used in authoring.
"""

SPECS = {
    "cf-1557-c": {
        "code": r"""#include <bits/stdc++.h>
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
""",
        "algorithm": (
            "Process bit columns from most significant to least significant with counts "
            "for AND and XOR prefixes being equal or AND being greater. An odd n has "
            "2^(n-1)+1 equal columns and no greater column; an even n has 2^(n-1)-1 "
            "equal columns and one greater column. Once greater, all 2^n columns are allowed."
        ),
        "proof": (
            "Exactly half of n-bit columns have even parity. The all-one column must be "
            "treated separately: it has AND=1 and XOR=n mod 2. Every other column has "
            "AND=0. Thus the listed equal and greater multiplicities are exhaustive. "
            "Lexicographic comparison of binary representations is decided by the first "
            "unequal bit, giving the two-state recurrence. The equal and greater terminal "
            "states partition all winning arrays."
        ),
        "time": "O(log n + k) per test case",
        "space": "O(1) auxiliary space",
        "invariants": [
            "equal counts exactly assignments with equal processed AND and XOR prefixes.",
            "greater counts assignments whose processed AND prefix is already greater.",
            "The previous equal count is used before the equal state is updated.",
        ],
        "traps": [
            "The all-one column is equal for odd n but strictly greater for even n.",
            "Winning means greater than or equal, so equality must be included.",
            "A decided greater prefix permits every assignment of subsequent columns.",
        ],
        "edges": ["k=0 has exactly the all-zero array.", "n=1 makes every array winning."],
        "steps": [
            "Count even-parity bit columns as 2^(n-1).",
            "Classify the all-one column according to the parity of n.",
            "Maintain equal and greater comparison states from high bits to low bits.",
            "Extend a greater state by all 2^n possible columns.",
            "Return the sum of equal and greater states modulo 1000000007.",
        ],
        "mutants": [
            {
                "old": "ll greater_choices = (n % 2 == 0 ? 1 : 0);",
                "new": "ll greater_choices = (n % 2 == 1 ? 1 : 0);",
                "claim": "The all-one column makes AND strictly larger precisely when n is odd.",
                "taxonomy": "algorithm_logic",
            },
            {
                "old": "greater * all + equal * greater_choices",
                "new": "greater * equal_choices + equal * greater_choices",
                "claim": "Even after a greater prefix, lower columns must preserve equality.",
                "taxonomy": "algorithm_logic",
            },
        ],
    },
    "cf-1567-c": {
        "code": r"""#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int t; cin >> t;
    while (t--) {
        string s; cin >> s;
        long long lane[2] = {0, 0};
        for (int i = 0; i < (int)s.size(); ++i)
            lane[i % 2] = lane[i % 2] * 10 + (s[i] - '0');
        cout << (lane[0] + 1) * (lane[1] + 1) - 2 << '\n';
    }
}
""",
        "algorithm": (
            "Split the decimal digits of n into the two alternating-position strings. "
            "Interpret them as ordinary decimal integers A and B. The answer is "
            "(A+1)(B+1)-2."
        ),
        "proof": (
            "Carrying two columns left never crosses digit parity, so the two lanes are "
            "independent ordinary additions. A lane with target A has A+1 ordered "
            "nonnegative addend pairs. Interleaving two lane decompositions bijectively "
            "recovers a pair of nonnegative original integers, including leading zeroes. "
            "The two pairs with one full addend zero must be removed; they are distinct "
            "because n is positive."
        ),
        "time": "O(log n) per test case",
        "space": "O(log n) for the input string and O(1) additional space",
        "invariants": [
            "Each lane preserves the order of digits from its own alternating positions.",
            "Carry propagation remains entirely within its lane.",
        ],
        "traps": [
            "The addends are positive, requiring removal of two zero-addend cases.",
            "Digits in a lane form a decimal number rather than an unordered digit sum.",
        ],
        "edges": [
            "A one-digit n leaves the second lane equal to zero.",
            "Internal zeroes retain their positional significance.",
        ],
        "steps": [
            "Separate alternating digit positions into two independent carry lanes.",
            "Read each lane as an ordinary decimal target.",
            "Multiply the numbers of ordered nonnegative decompositions of both lanes.",
            "Exclude the two pairs with a zero original addend.",
        ],
        "mutants": [
            {
                "old": "(lane[0] + 1) * (lane[1] + 1) - 2",
                "new": "(lane[0] + 1) * (lane[1] + 1)",
                ("claim"): (
                    "Lane decompositions already guarantee that both original addends are positive."
                ),
                "taxonomy": "constraint_omission",
            },
            {
                "old": "lane[i % 2] * 10 + (s[i] - '0')",
                "new": "lane[i % 2] + (s[i] - '0')",
                "claim": "Each independent carry lane is represented by the sum of its digits.",
                "taxonomy": "algorithm_logic",
            },
        ],
    },
    "cf-1575-l": {
        "code": r"""#include <bits/stdc++.h>
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
        if (a <= i) points.push_back({a, i - a});
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
""",
        "algorithm": (
            "For a potential fixed point at original index i, define its required "
            "deletion count d=i-a_i and discard d<0. A feasible chain has strictly "
            "increasing a_i and nondecreasing d. Sort candidates by a_i and compute the "
            "longest chain using a Fenwick maximum over d, batching updates for equal a_i."
        ),
        "proof": (
            "If two selected fixed points have original indices i<j, their final indices "
            "must satisfy a_i<a_j and the number of deletions before them cannot decrease, "
            "so i-a_i<=j-a_j. Conversely these two inequalities ensure sufficient "
            "intermediate elements to fill exactly a_j-a_i-1 retained positions. The "
            "first point can be placed at a_i because i>=a_i. Therefore every such chain "
            "can be realized as fixed points of a retained subsequence. The Fenwick "
            "recurrence enumerates exactly its feasible predecessors; batching excludes "
            "equal final indices."
        ),
        "time": "O(n log n)",
        "space": "O(n)",
        "invariants": [
            "Only points with nonnegative required deletion counts are retained.",
            "Before a value group, the Fenwick tree contains only strictly smaller a_i.",
            "A prefix maximum includes all predecessor deletion counts at most d.",
        ],
        "traps": [
            "Fixed points need not form a contiguous sequence of final indices.",
            "Equal a_i cannot both become fixed points.",
            "Equal deletion counts are compatible and must be allowed.",
        ],
        "edges": [
            "No index with a_i<=i gives answer zero.",
            "An already fixed sequence allows repeated deletion count zero.",
        ],
        "steps": [
            "Represent each eligible fixed point by its target index and deletion count.",
            "Derive strict growth of target indices and nondecreasing deletion counts.",
            "Sort points by target index and query the maximum compatible predecessor.",
            "Delay all updates within an equal-target group.",
            "Take the maximum chain length, which is realizable by filling intervening positions.",
        ],
        "mutants": [
            {
                "old": "int answer = 0;",
                "new": "int answer = 1;",
                "claim": "Every nonempty input allows at least one fixed point after deletions.",
                "taxonomy": "boundary_error",
            },
            {
                "old": "if (a <= i) points.push_back({a, i - a});",
                "new": "if (a < i) points.push_back({a, i - a});",
                "claim": "A position can contribute only after at least one preceding deletion.",
                "taxonomy": "boundary_error",
            },
        ],
    },
    "cf-1606-e": {
        "code": r"""#include <bits/stdc++.h>
using namespace std;
using ll = long long;
const int MOD = 998244353;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int n, x; cin >> n >> x;
    int lim = max(n, x);
    vector<vector<int>> choose(n + 1, vector<int>(n + 1));
    vector<vector<int>> pw(lim + 1, vector<int>(n + 1, 1));
    for (int b = 0; b <= lim; ++b)
        for (int e = 1; e <= n; ++e) pw[b][e] = (ll)pw[b][e-1] * b % MOD;
    choose[0][0] = 1;
    for (int i = 1; i <= n; ++i) {
        choose[i][0] = choose[i][i] = 1;
        for (int j = 1; j < i; ++j)
            choose[i][j] = (choose[i-1][j-1] + choose[i-1][j]) % MOD;
    }
    vector<vector<int>> dp(n + 1, vector<int>(x + 1));
    for (int h = 0; h <= x; ++h) dp[0][h] = 1;
    for (int h = 1; h <= x; ++h) {
        for (int alive = 2; alive <= n; ++alive) {
            if (h <= alive - 1) {
                dp[alive][h] = pw[h][alive];
                continue;
            }
            int remaining = h - (alive - 1);
            ll ways = 0;
            for (int survive = 0; survive <= alive; ++survive) {
                ll term = (ll)choose[alive][survive] * pw[alive-1][alive-survive] % MOD;
                ways = (ways + term * dp[survive][remaining]) % MOD;
            }
            dp[alive][h] = ways;
        }
    }
    cout << dp[n][x] << '\n';
}
""",
        "algorithm": (
            "Let dp[c][h] count health assignments in [1,h] for c labelled surviving "
            "heroes that yield no winner. Set dp[0][h]=1 and dp[1][h]=0. With c>=2, "
            "everyone takes c-1 damage. If h<=c-1 every assignment dies immediately. "
            "Otherwise sum over s first-round survivors: C(c,s)(c-1)^(c-s) "
            "dp[s][h-c+1]. Precompute binomials and powers and fill increasing h."
        ),
        "proof": (
            "A first round uniquely partitions heroes into those with health at most "
            "c-1 and the surviving labelled subset. Each dead hero has c-1 choices, "
            "and subtracting c-1 from survivor health bijectively maps it into [1,h-c+1]. "
            "Subsequent rounds depend only on these residual health values. Zero "
            "survivors is a successful terminal state and one survivor is a winner, "
            "hence the base cases. The recurrence is disjoint and exhaustive, including "
            "the case in which every hero survives a round. The health bound strictly "
            "decreases in every recursive reference."
        ),
        "time": "O(n^2 x + n max(n,x))",
        "space": "O(nx + n^2 + n max(n,x))",
        "invariants": [
            "dp[1][h] is zero because one remaining hero is already a winner.",
            "A transition reduces the common residual health bound by alive-1.",
            (
                "Combinations choose labelled survivors and powers independently count "
                "dead health values."
            ),
        ],
        "traps": [
            (
                "Damage is simultaneous; a hero alive at round start contributes d"
                "amage even if killed."
            ),
            "The all-survive transition is necessary when health is large.",
            "A hero does not damage itself.",
        ],
        "edges": [
            "x<=n-1 makes all x^n assignments have no winner.",
            "With two heroes, exactly equal initial health values yield no winner.",
        ],
        "steps": [
            "Use the number of alive heroes and their common health bound as the state.",
            "Count immediate total deaths directly when the bound is at most alive-1.",
            "Choose the survivor subset and independently assign health to killed heroes.",
            "Translate surviving health values by the simultaneous damage alive-1.",
            "Sum residual states while rejecting exactly one survivor.",
        ],
        "mutants": [
            {
                "old": "for (int survive = 0; survive <= alive; ++survive)",
                "new": "for (int survive = 0; survive < alive; ++survive)",
                "claim": "Every simulated round must kill at least one hero.",
                "taxonomy": "algorithm_logic",
            },
            {
                "old": "int remaining = h - (alive - 1);",
                "new": "int remaining = h - alive;",
                ("claim"): (
                    "Each surviving hero loses one health point for every hero, including itself."
                ),
                "taxonomy": "problem_misread",
            },
        ],
    },
    "cf-1549-c": {
        "code": r"""#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int n, m; cin >> n >> m;
    vector<int> higher(n + 1);
    int answer = n;
    auto add = [&](int u, int v) {
        if (u > v) swap(u, v);
        if (higher[u]++ == 0) --answer;
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
""",
        "algorithm": (
            "Maintain, for every noble, its number of friends with a larger label. "
            "The survivors of the complete elimination process are exactly nobles "
            "whose count is zero. Each edge changes only the count of its smaller "
            "endpoint, and the answer changes only when that count crosses zero."
        ),
        "proof": (
            "For an edge u<v, v cannot be killed while u is alive because u is a "
            "weaker friend. A noble with no higher friend can therefore never be "
            "vulnerable: while it has friends they are weaker, and otherwise it is "
            "isolated. Inducting over increasing labels, every noble with a higher "
            "friend eventually loses all its lower friends; those lower friends "
            "have this noble as a higher friend and die first. Its higher friend "
            "is still alive, so the noble is then killed. Thus zero higher-degree "
            "is exactly the survivor predicate."
        ),
        "time": "O(n + m + q)",
        "space": "O(n)",
        "invariants": [
            "higher[u] counts current friendships from u to a larger label.",
            "answer equals the number of vertices with higher count zero.",
            "Type 3 queries inspect the graph without carrying out permanent eliminations.",
        ],
        "traps": [
            "Having any weaker friend protects a noble only temporarily.",
            "Multiple higher friends still contribute only one lost survivor.",
        ],
        "edges": [
            "An edgeless graph leaves all n nobles alive.",
            "Removing the last higher friend restores one survivor.",
        ],
        "steps": [
            "Prove that every noble with a higher friend is eliminated before that friend.",
            "Identify zero higher-degree vertices as exactly the survivors.",
            "Update only the smaller endpoint of each added or removed edge.",
            "Adjust the global answer only at zero-count transitions.",
        ],
        "mutants": [
            {
                "old": "if (higher[u]++ == 0) --answer;",
                "new": "++higher[u]; --answer;",
                "claim": (
                    "Every added friendship removes another surviving noble even if its wea"
                    "ker endpoint was already doomed."
                ),
                "taxonomy": "algorithm_logic",
            },
            {
                "old": "int answer = n;",
                "new": "int answer = n - 1;",
                "claim": "An edgeless n-vertex graph starts with only n-1 surviving nobles.",
                "taxonomy": "boundary_error",
            },
        ],
    },
    "cf-1581-b": {
        "code": r"""#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int t; cin >> t;
    while (t--) {
        long long n, m, k; cin >> n >> m >> k;
        long long complete = n * (n - 1) / 2;
        bool possible = false;
        if (m >= n - 1 && m <= complete) {
            long long diameter = (n == 1 ? 0 : (m == complete ? 1 : 2));
            possible = diameter < k - 1;
        }
        cout << (possible ? "YES" : "NO") << '\n';
    }
}
""",
        "algorithm": (
            "Reject edge counts below n-1 or above n(n-1)/2. The smallest possible "
            "diameter is zero for a singleton, one for a complete graph with at least "
            "two vertices, and two otherwise. Compare this minimum strictly with k-1."
        ),
        "proof": (
            "A connected simple graph needs at least n-1 edges and has at most one "
            "edge per unordered pair. For n>1, diameter one is equivalent to being "
            "complete. Every other admissible edge count is achieved by a star plus "
            "arbitrary unused edges. This construction has diameter at most two, and "
            "its missing edge forces diameter at least two. These lower bounds and "
            "constructions give the exact minimum used in the strict comparison."
        ),
        "time": "O(1) per test case",
        "space": "O(1)",
        "invariants": [
            "Only edge counts feasible for connected simple graphs reach the diameter check.",
            "The computed diameter is the minimum achievable with exactly m edges.",
        ],
        "traps": [
            "The condition is strictly less than k-1.",
            "Compute n(n-1) using 64-bit arithmetic.",
        ],
        "edges": [
            "n=1 requires m=0 and has diameter zero.",
            "A complete graph with n>1 has diameter one.",
        ],
        "steps": [
            "Check the connected simple graph bounds on the number of edges.",
            "Handle the singleton's diameter zero.",
            "Distinguish a complete graph from all other admissible graphs.",
            "Use a star with extra edges to attain diameter two in the remaining case.",
            "Apply the required strict diameter inequality.",
        ],
        "mutants": [
            {
                "old": "possible = diameter < k - 1;",
                "new": "possible = diameter <= k - 1;",
                "claim": "The graph may have diameter equal to k-1.",
                "taxonomy": "boundary_error",
            },
            {
                "old": "if (m >= n - 1 && m <= complete)",
                "new": "if (m <= complete)",
                "claim": (
                    "Any simple graph edge count admits the computed diameter, even below t"
                    "he connectivity bound."
                ),
                "taxonomy": "constraint_omission",
            },
        ],
    },
    "cf-1552-d": {
        "code": r"""#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int t; cin >> t;
    while (t--) {
        int n; cin >> n;
        vector<long long> a(n), sums(1 << n);
        for (auto &x : a) cin >> x;
        unordered_set<long long> seen;
        seen.reserve(2 << n);
        seen.insert(0);
        bool possible = false;
        for (int mask = 1; mask < (1 << n); ++mask) {
            int bit = __builtin_ctz((unsigned)mask);
            sums[mask] = sums[mask ^ (1 << bit)] + a[bit];
            if (!seen.insert(sums[mask]).second) possible = true;
        }
        cout << (possible ? "YES" : "NO") << '\n';
    }
}
""",
        "algorithm": (
            "Enumerate all subset sums, including the empty subset's zero. Output "
            "YES exactly when two different subsets have the same sum. This is "
            "equivalent to a nonempty signed relation with coefficients in {-1,0,1}."
        ),
        "proof": (
            "Any representation a_i=b_j-b_k gives a multigraph with n vertices and "
            "n labelled edges. It contains a cycle, including a possible loop or "
            "parallel-edge cycle, and summing the directed differences around it "
            "gives a nonempty signed zero relation. Conversely, a signed relation "
            "on r entries constructs a closed walk on r vertex potentials by "
            "successive signed sums. Each of the remaining n-r entries can be "
            "represented by attaching one new vertex to an existing vertex, using "
            "at most n potentials. A signed relation is equivalent to two distinct "
            "equal-sum subsets after cancelling their intersection."
        ),
        "time": "Expected O(2^n) per test case with hashing",
        "space": "O(2^n)",
        "invariants": [
            "sums[mask] is the sum over exactly the indices set in mask.",
            "seen contains the sums of all previously enumerated subsets, including the empty one.",
        ],
        "traps": [
            "The signed relation can involve more than two array entries.",
            "Zero is itself a valid one-entry relation because j and k may coincide.",
            "Equal values at distinct array positions remain distinct labelled entries.",
        ],
        "edges": [
            "For n=1 only a_1=0 is possible.",
            "Negative values do not require special handling.",
        ],
        "steps": [
            "View each required difference as a labelled edge between n potential values.",
            "Use a cycle to prove the necessity of a nonempty signed zero relation.",
            "Construct potentials from any such relation to establish sufficiency.",
            "Translate the signed relation into equality of two distinct subset sums.",
            "Enumerate the at most 1024 subset sums and detect a duplicate.",
        ],
        "mutants": [
            {
                "old": "seen.insert(0);",
                "new": "// The empty subset is omitted.",
                "claim": "Only two nonempty subsets may witness an admissible signed relation.",
                "taxonomy": "constraint_omission",
            },
            {
                "old": "if (!seen.insert(sums[mask]).second) possible = true;",
                "new": (
                    "if (__builtin_popcount((unsigned)mask) == 1 && !seen.insert(sums[mask]"
                    ").second) possible = true;"
                ),
                "claim": (
                    "A zero entry or equal pair of entries is necessary, so sums of larger "
                    "subsets can be ignored."
                ),
                "taxonomy": "algorithm_logic",
            },
        ],
    },
    "cf-1608-c": {
        "code": r"""#include <bits/stdc++.h>
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
""",
        "algorithm": (
            "Create a directed beat relation, compressed to adjacent stronger-to-weaker "
            "edges in each sorted map ranking. Reverse these edges and traverse from "
            "the strongest player on the first map. Exactly the visited players can win."
        ),
        "proof": (
            "The adjacent ranking chains preserve reachability of the full beat graph: "
            "any stronger player reaches every weaker player through its map's chain. "
            "A player can win a tournament exactly when it reaches all players in the "
            "beat graph. Necessity follows by tracing the elimination tree; sufficiency "
            "follows by taking an outward spanning tree and eliminating descendants "
            "before their parents. The strongest first-map player reaches everyone, "
            "so a player reaches everyone precisely when it reaches that player. "
            "Reverse traversal computes exactly this predecessor set."
        ),
        "time": "O(n log n) per test case",
        "space": "O(n)",
        "invariants": [
            (
                "Every reversed edge points from a weaker player to an adjacent stronge"
                "r player on one map."
            ),
            "A marked player can reach the strongest first-map player in the original beat graph.",
        ],
        "traps": [
            (
                "Winning eligibility is transitive through other eliminations, not just"
                " direct strength maxima."
            ),
            "Both map rankings must contribute to reachability.",
        ],
        "edges": [
            "A single player wins automatically.",
            "Identical map orders leave only their maximum eligible.",
        ],
        "steps": [
            "Model each permitted match winner-to-loser relation as a directed edge.",
            "Replace each map's dense relation with its adjacent ranking chain.",
            "Prove tournament winners are exactly vertices that reach all others.",
            "Reduce universal reachability to reaching the strongest first-map player.",
            "Traverse reversed chain edges and output the visited set in original order.",
        ],
        "mutants": [
            {
                "old": "rev[by_b[i - 1]].push_back(by_b[i]);",
                "new": "// Only first-map edges are retained.",
                "claim": "The first-map ranking alone determines all possible tournament winners.",
                "taxonomy": "constraint_omission",
            },
            {
                "old": "todo.push(by_a.back()); answer[by_a.back()] = '1';",
                "new": "todo.push(by_a.front()); answer[by_a.front()] = '1';",
                ("claim"): (
                    "Reaching the weakest first-map player is enough to guarantee a to"
                    "urnament victory."
                ),
                "taxonomy": "algorithm_logic",
            },
        ],
    },
    "cf-1608-d": {
        "code": (
            "#include <bits/stdc++.h>\n"
            "using namespace std;\n"
            "using ll = long long;\n"
            "const ll MOD = 998244353;\n"
            "ll power(ll a, ll e) {\n"
            "    ll r = 1;\n"
            "    while (e) {\n"
            "        if (e & 1) r = r * a % MOD;\n"
            "        a = a * a % MOD; e >>= 1;\n"
            "    }\n"
            "    return r;\n"
            "}\n"
            "int main() {\n"
            "    ios::sync_with_stdio(false); cin.tie(nullptr);\n"
            "    int n; cin >> n;\n"
            "    int blacks = 0, unknown = 0;\n"
            "    ll mixed = 1;\n"
            "    bool all_bw = true, all_wb = true;\n"
            "    for (int i = 0; i < n; ++i) {\n"
            "        string s; cin >> s;\n"
            "        for (char c : s) { blacks += (c == 'B'); unknown += (c == '?')"
            "; }\n"
            "        bool bw = (s[0] != 'W' && s[1] != 'B');\n"
            "        bool wb = (s[0] != 'B' && s[1] != 'W');\n"
            "        mixed = mixed * (int(bw) + int(wb)) % MOD;\n"
            "        all_bw = all_bw && bw;\n"
            "        all_wb = all_wb && wb;\n"
            "    }\n"
            "    vector<ll> fact(unknown + 1, 1);\n"
            "    for (int i = 1; i <= unknown; ++i) fact[i] = fact[i-1] * i % MOD;\n"
            "    int need = n - blacks;\n"
            "    ll balanced = 0;\n"
            "    if (0 <= need && need <= unknown)\n"
            "        balanced = fact[unknown] * power(fact[need], MOD-2) % MOD * po"
            "wer(fact[unknown-need], MOD-2) % MOD;\n"
            "    ll answer = (balanced - mixed + int(all_bw) + int(all_wb)) % MOD;\n"
            "    if (answer < 0) answer += MOD;\n"
            "    cout << answer << '\\n';\n"
            "}\n"
        ),
        "algorithm": (
            "First count completions with exactly n black cells by a binomial coefficient. "
            "Subtract all completions in which every domino is BW or WB, using the product "
            "of local compatibility counts. Restore the all-BW and all-WB completions "
            "when compatible with the fixed cells."
        ),
        "proof": (
            "Represent a domino as a directed edge from its left color to the opposite "
            "of its right color. A valid cyclic ordering is an Euler circuit in this "
            "two-vertex multigraph. Degree balance is BB=WW, equivalently exactly n "
            "black cells overall. If BB and WW are present, this balanced graph is "
            "connected on its nonzero-degree vertices and has an Euler circuit. If "
            "neither is present, all edges are loops: an Euler circuit exists only "
            "when all dominoes have the same orientation BW or WB. The subtraction "
            "and restoration count exactly these exceptional disconnected cases."
        ),
        "time": "O(n + log MOD)",
        "space": "O(n)",
        "invariants": [
            (
                "balanced counts exactly completions with equal total numbers of b"
                "lack and white cells."
            ),
            "mixed counts completions using only BW and WB dominoes.",
            "all_bw and all_wb each represent one possible monochromatic loop family.",
        ],
        "traps": [
            "Equal total color counts alone do not guarantee a valid cyclic ordering.",
            "Dominoes cannot be rotated.",
            (
                "The original positions distinguish different colorings even though rea"
                "rrangement is permitted."
            ),
        ],
        "edges": [
            "For n=1 only BW and WB are valid.",
            "An infeasible binomial choice contributes zero.",
        ],
        "steps": [
            "Transform each domino into an edge from its left color to the opposite right color.",
            "Reduce degree balance to a total of exactly n black cells.",
            "Count balanced completions by choosing the needed unknown black cells.",
            "Identify disconnected balanced graphs as mixtures of BW and WB loops.",
            "Subtract all loop-only completions and restore each uniform orientation.",
        ],
        "mutants": [
            {
                "old": "balanced - mixed + int(all_bw) + int(all_wb)",
                "new": "balanced + int(all_bw) + int(all_wb)",
                "claim": (
                    "Balanced color counts already ensure connectivity, so mixed loop famil"
                    "ies need not be excluded."
                ),
                "taxonomy": "algorithm_logic",
            },
            {
                "old": "balanced - mixed + int(all_bw) + int(all_wb)",
                "new": "balanced - mixed + int(all_bw)",
                "claim": "A uniform WB cycle is invalid because dominoes cannot be rotated.",
                "taxonomy": "problem_misread",
            },
        ],
    },
    "cf-1613-e": {
        "code": (
            "#include <bits/stdc++.h>\n"
            "using namespace std;\n"
            "int main() {\n"
            "    ios::sync_with_stdio(false); cin.tie(nullptr);\n"
            "    int t; cin >> t;\n"
            "    const int dr[4] = {-1, 1, 0, 0};\n"
            "    const int dc[4] = {0, 0, -1, 1};\n"
            "    while (t--) {\n"
            "        int n, m; cin >> n >> m;\n"
            "        vector<string> grid(n);\n"
            "        for (auto &row : grid) cin >> row;\n"
            "        vector<int> degree(n * m);\n"
            "        queue<int> todo;\n"
            "        for (int r = 0; r < n; ++r) for (int c = 0; c < m; ++c) {\n"
            "            if (grid[r][c] == '#') continue;\n"
            "            int u = r * m + c;\n"
            "            if (grid[r][c] == 'L') todo.push(u);\n"
            "            for (int d = 0; d < 4; ++d) {\n"
            "                int nr = r + dr[d], nc = c + dc[d];\n"
            "                if (0 <= nr && nr < n && 0 <= nc && nc < m && grid[nr]"
            "[nc] != '#') ++degree[u];\n"
            "            }\n"
            "        }\n"
            "        while (!todo.empty()) {\n"
            "            int u = todo.front(); todo.pop();\n"
            "            int r = u / m, c = u % m;\n"
            "            for (int d = 0; d < 4; ++d) {\n"
            "                int nr = r + dr[d], nc = c + dc[d];\n"
            "                if (nr < 0 || nr >= n || nc < 0 || nc >= m || grid[nr]"
            "[nc] != '.') continue;\n"
            "                int v = nr * m + nc;\n"
            "                if (--degree[v] <= 1) {\n"
            "                    grid[nr][nc] = '+';\n"
            "                    todo.push(v);\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "        for (auto &row : grid) cout << row << '\\n';\n"
            "    }\n"
            "}\n"
        ),
        "algorithm": (
            "Start a queue with the lab. Store each free cell's number of free neighbors. "
            "When processing a cell already known to reach the lab, decrement this "
            "count for unmarked neighbors. Mark and enqueue a neighbor when at most "
            "one unresolved neighbor remains."
        ),
        "proof": (
            "A command can forbid exactly one direction. A cell adjacent to an already "
            "winning cell is winning when at most one neighbor is still unresolved: "
            "forbid that direction, and every legal move goes to an earlier winning "
            "cell. The lab starts this induction, and queue order supplies decreasing "
            "ranks along forced moves. At termination, every unmarked cell adjacent "
            "to the winning region has at least two unmarked neighbors, so after any "
            "command the adversary can stay outside. An unmarked cell with no winning "
            "neighbor can likewise stay outside or do nothing. Thus no unmarked cell "
            "can be forced into the lab."
        ),
        "time": "O(nm) per test case",
        "space": "O(nm)",
        "invariants": [
            "Every queued cell already has a strategy that reaches the lab.",
            "For an unmarked cell, degree counts neighbors not yet processed from the queue.",
            "Each cell is marked and queued at most once.",
        ],
        "traps": [
            (
                "Ordinary reachability from the lab is insufficient against adversarial"
                " direction choices."
            ),
            "The controller can forbid only one unresolved direction.",
            "Isolated dead ends disconnected from the lab must not be seeded as winning.",
        ],
        "edges": ["A one-cell lab remains L.", "Walls and the lab symbol must be preserved."],
        "steps": [
            "Count all nonblocked neighbors of each free cell.",
            "Initialize the known winning region with the lab.",
            "Remove each processed winning neighbor from surrounding unresolved degrees.",
            "Mark a neighbor once a command can forbid its only possible unresolved exit.",
            "Use the remaining region's closure under adversarial responses to prove completeness.",
        ],
        "mutants": [
            {
                "old": "if (--degree[v] <= 1)",
                "new": "if (--degree[v] <= 2)",
                "claim": "One command can exclude two unresolved neighboring directions.",
                "taxonomy": "algorithm_logic",
            },
            {
                "old": "if (--degree[v] <= 1)",
                "new": "if (degree[v] <= 1)",
                "claim": (
                    "Initial free degree can be used throughout because newly winning neigh"
                    "bors do not change the forcing condition."
                ),
                "taxonomy": "implementation_error",
            },
        ],
    },
    "cf-1553-d": {
        "code": r"""#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int q; cin >> q;
    while (q--) {
        string s, t; cin >> s >> t;
        int i = (int)s.size() - 1, j = (int)t.size() - 1;
        while (i >= 0 && j >= 0) {
            if (s[i] == t[j]) { --i; --j; }
            else i -= 2;
        }
        cout << (j < 0 ? "YES" : "NO") << '\n';
    }
}
""",
        "algorithm": (
            "Match the target from right to left. If the current source and target "
            "characters agree, consume both. Otherwise discard two source positions, "
            "representing a typed character cancelled by a backspace. Success means "
            "the whole target has been consumed; any remaining source prefix can be "
            "typed entirely as backspaces on an empty string."
        ),
        "proof": (
            "After the final retained character, discarded operations form balanced "
            "type/backspace pairs, so their length is even. The same parity condition "
            "holds between successive retained target characters. Scanning by two "
            "therefore enumerates exactly the possible positions for the next target "
            "character. Choosing the rightmost matching candidate cannot hurt: any "
            "earlier candidate has the same parity, and replacing it by the later "
            "one makes an additional even block available before it. The unmatched "
            "initial prefix has no parity restriction because backspacing an empty "
            "string is allowed."
        ),
        "time": "O(|s| + |t|) per test case including input",
        "space": "O(|s| + |t|) for strings and O(1) additional space",
        "invariants": [
            "The suffix of t after j has already been matched to retained source positions.",
            "Skipped positions to the right of the unmatched source prefix occur in pairs.",
        ],
        "traps": [
            "This is not ordinary subsequence matching: internal deletions have even length.",
            "A leading unmatched prefix may have odd length.",
        ],
        "edges": ["A longer target cannot be produced.", "Equal strings require no backspaces."],
        "steps": [
            "Work backward from the final required target character.",
            "Use the parity of cancelled type/backspace operations to skip mismatches in pairs.",
            "Greedily keep the latest matching character of the admissible parity.",
            (
                "Accept once all target characters are matched because the leading sour"
                "ce prefix can be erased freely."
            ),
        ],
        "mutants": [
            {
                "old": "else i -= 2;",
                "new": "else i -= 1;",
                "claim": (
                    "An arbitrary individual source character can be deleted without consum"
                    "ing a second operation."
                ),
                "taxonomy": "problem_misread",
            },
            {
                "old": 'j < 0 ? "YES" : "NO"',
                "new": '(j < 0 && (i + 1) % 2 == 0) ? "YES" : "NO"',
                ("claim"): (
                    "The discarded leading prefix must also contain an even number of operations."
                ),
                "taxonomy": "boundary_error",
            },
        ],
    },
    "cf-1618-d": {
        "code": r"""#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int t; cin >> t;
    while (t--) {
        int n, k; cin >> n >> k;
        vector<int> a(n);
        for (int &x : a) cin >> x;
        sort(a.begin(), a.end());
        long long answer = 0;
        int keep = n - 2 * k;
        for (int i = 0; i < keep; ++i) answer += a[i];
        for (int i = 0; i < k; ++i)
            answer += (a[keep + i] == a[keep + k + i]);
        cout << answer << '\n';
    }
}
""",
        "algorithm": (
            "Sort the array and leave the smallest n-2k elements unpaired. Split the "
            "largest 2k elements into sorted halves of length k and pair corresponding "
            "positions across the halves. Each pair contributes one if equal and zero "
            "otherwise; add the retained prefix sum."
        ),
        "proof": (
            "Orient every pair with its smaller value as numerator, making its cost "
            "zero or one. If a smaller used value y and a larger retained value x "
            "are exchanged, the retained sum drops by x-y while pair cost can rise "
            "by at most one. Distinct integers have x-y>=1, and equal values change "
            "nothing, so keeping the smallest elements is optimal. Among 2k selected "
            "values, a frequency f>k forces at least f-k equal pairs. Pairing sorted "
            "positions distance k apart has exactly max(0,f-k) equal pairs for each "
            "value's contiguous run. At most one frequency exceeds k, so this reaches "
            "the unavoidable lower bound."
        ),
        "time": "O(n log n) per test case",
        "space": "O(n)",
        "invariants": [
            "The retained prefix consists of the smallest n-2k values.",
            "Each selected index is used exactly once in a pair.",
            "Every pair's numerator is no larger than its denominator.",
        ],
        "traps": [
            "Equal pairs contribute one rather than zero.",
            "Pairing adjacent selected values can create avoidable equal pairs.",
        ],
        "edges": [
            "k=0 returns the entire array sum.",
            "n=2k leaves no retained values.",
            "All equal values force k unit-cost pairs.",
        ],
        "steps": [
            (
                "Orient each division so that pair cost is zero for unequal values and "
                "one for equal values."
            ),
            "Use an exchange argument to retain the smallest n-2k values.",
            "Bound unavoidable equal pairs by any value frequency exceeding k.",
            "Pair sorted selected positions k apart to attain that bound.",
            "Add the retained prefix sum and the equal-pair count.",
        ],
        "mutants": [
            {
                "old": "answer += (a[keep + i] == a[keep + k + i]);",
                "new": "answer += (a[keep + 2 * i] == a[keep + 2 * i + 1]);",
                ("claim"): (
                    "Pairing adjacent sorted selected values always minimizes the numb"
                    "er of equal pairs."
                ),
                "taxonomy": "algorithm_logic",
            },
            {
                "old": "answer += (a[keep + i] == a[keep + k + i]);",
                "new": "answer += (a[keep + i] < a[keep + k + i]);",
                ("claim"): (
                    "A strict smaller-over-larger pair contributes one while an equal "
                    "pair contributes zero."
                ),
                "taxonomy": "problem_misread",
            },
        ],
    },
    "cf-1554-b": {
        "code": r"""#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int t; cin >> t;
    while (t--) {
        int n, k; cin >> n >> k;
        vector<int> a(n + 1);
        for (int i = 1; i <= n; ++i) cin >> a[i];
        long long answer = LLONG_MIN;
        int first = max(1, n - 2 * k);
        for (int i = first; i <= n; ++i)
            for (int j = i + 1; j <= n; ++j)
                answer = max(answer, 1LL * i * j - 1LL * k * (a[i] | a[j]));
        cout << answer << '\n';
    }
}
""",
        "algorithm": (
            "Read all values but enumerate pairs only in the index suffix beginning "
            "at max(1,n-2k). This contains at most 2k+1 indices. Evaluate the original "
            "index product and bitwise OR penalty exactly using 64-bit arithmetic."
        ),
        "proof": (
            "For values at most n, their bitwise OR is strictly below 2n: it is at "
            "most their sum, and equality with 2n would require both values n, whose "
            "OR is only n. Therefore the pair (n-1,n) scores strictly more than "
            "n(n-1)-2kn. If i<n-2k, then i*j<=n(n-2k-1)=n(n-1)-2kn, and the "
            "nonnegative penalty cannot improve this upper bound. Such a pair cannot "
            "be optimal. Every remaining pair is directly enumerated."
        ),
        "time": "O(n + k^2) per test case",
        "space": "O(n)",
        "invariants": [
            "All unexamined pairs are dominated by the available pair (n-1,n).",
            "The objective uses original one-based indices, even within the shortened suffix.",
        ],
        "traps": [
            "Bitwise OR is different from XOR and from arithmetic sum.",
            "The best score may be negative.",
            "The index product can exceed 32-bit range.",
        ],
        "edges": ["When n<=2k the full array is searched.", "n=2 has exactly one candidate pair."],
        "steps": [
            "Bound every OR penalty by a value strictly smaller than 2kn.",
            "Use the last two indices to obtain a global feasible lower bound.",
            "Show any pair starting before n-2k is below that bound even without its penalty.",
            "Enumerate the remaining O(k^2) pairs using the exact 64-bit objective.",
        ],
        "mutants": [
            {
                "old": "(a[i] | a[j])",
                "new": "(a[i] ^ a[j])",
                ("claim"): (
                    "Bits set in both values cancel when computing the objective's bitwise penalty."
                ),
                "taxonomy": "problem_misread",
            },
            {
                "old": "long long answer = LLONG_MIN;",
                "new": "long long answer = 0;",
                ("claim"): (
                    "The maximum objective is always nonnegative, so zero is a valid i"
                    "nitial lower bound."
                ),
                "taxonomy": "boundary_error",
            },
        ],
    },
    "cf-1579-e2": {
        "code": (
            "#include <bits/stdc++.h>\n"
            "using namespace std;\n"
            "struct Fenwick {\n"
            "    int n; vector<int> bit;\n"
            "    explicit Fenwick(int n): n(n), bit(n + 1) {}\n"
            "    int sum(int p) {\n"
            "        int r = 0;\n"
            "        for (; p > 0; p -= p & -p) r += bit[p];\n"
            "        return r;\n"
            "    }\n"
            "    void add(int p) {\n"
            "        for (; p <= n; p += p & -p) ++bit[p];\n"
            "    }\n"
            "};\n"
            "int main() {\n"
            "    ios::sync_with_stdio(false); cin.tie(nullptr);\n"
            "    int t; cin >> t;\n"
            "    while (t--) {\n"
            "        int n; cin >> n;\n"
            "        vector<int> a(n);\n"
            "        for (int &x : a) cin >> x;\n"
            "        vector<int> values = a;\n"
            "        sort(values.begin(), values.end());\n"
            "        values.erase(unique(values.begin(), values.end()), values.end("
            "));\n"
            "        Fenwick fw(values.size());\n"
            "        long long answer = 0;\n"
            "        for (int i = 0; i < n; ++i) {\n"
            "            int rank = lower_bound(values.begin(), values.end(), a[i])"
            " - values.begin() + 1;\n"
            "            int smaller = fw.sum(rank - 1);\n"
            "            int larger = i - fw.sum(rank);\n"
            "            answer += min(smaller, larger);\n"
            "            fw.add(rank);\n"
            "        }\n"
            "        cout << answer << '\\n';\n"
            "    }\n"
            "}\n"
        ),
        "algorithm": (
            "Compress the values and maintain frequencies of already processed "
            "elements in a Fenwick tree. Inserting the new value at the front adds "
            "one inversion for each strictly smaller earlier value, while inserting "
            "at the back adds one for each strictly larger value. Add the smaller "
            "of these counts, then insert the frequency."
        ),
        "proof": (
            "A new element is placed entirely before or entirely after the existing "
            "deque, so its inversion contribution depends only on the multiset of "
            "earlier values, not their arrangement. This choice leaves old inversions "
            "unchanged and does not alter the multiset seen by later steps. Therefore "
            "each step can independently minimize its contribution. Every inversion "
            "is counted exactly when its later-inserted member arrives, so the sum "
            "of these independently minimal contributions is globally optimal."
        ),
        "time": "O(n log n) per test case",
        "space": "O(n)",
        "invariants": [
            "Before processing index i, the Fenwick tree stores exactly the first i values.",
            "Equal values contribute no inversions on either insertion side.",
            "The accumulated score is the sum of optimal independent insertion contributions.",
        ],
        "traps": [
            "The counts are strictly smaller and strictly larger, excluding equality.",
            "Greedy decisions depend on the entire earlier multiset, not only deque endpoints.",
            "The total number of inversions requires 64-bit arithmetic.",
        ],
        "edges": [
            "An all-equal array has zero inversions.",
            "A singleton has zero cost.",
            "Negative values work through coordinate compression.",
        ],
        "steps": [
            (
                "Express the inversion cost of front insertion as the number of sm"
                "aller earlier values."
            ),
            "Express the cost of back insertion as the number of larger earlier values.",
            "Observe that the earlier multiset is independent of all previous placement choices.",
            "Query both strict counts with a compressed frequency Fenwick tree.",
            "Add their minimum and insert the current value's frequency.",
        ],
        "mutants": [
            {
                "old": "int smaller = fw.sum(rank - 1);",
                "new": "int smaller = fw.sum(rank);",
                ("claim"): (
                    "Putting a value at the front creates inversions with earlier equa"
                    "l values as well."
                ),
                "taxonomy": "boundary_error",
            },
            {
                "old": "int larger = i - fw.sum(rank);",
                "new": "int larger = i - fw.sum(rank - 1);",
                ("claim"): (
                    "Putting a value at the back creates inversions with earlier equal"
                    " values as well."
                ),
                "taxonomy": "boundary_error",
            },
        ],
    },
    "cf-1618-g": {
        "code": r"""#include <bits/stdc++.h>
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
        while (next_edge < (int)edges.size() && edges[next_edge].first <= k) {
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
""",
        "algorithm": (
            "Sort all items by price. For threshold k, connect adjacent prices whose "
            "gap is at most k. Each connected interval can give Monocarp its c largest "
            "prices, where c is his initial item count in that interval. Process "
            "queries and gaps in increasing order using a DSU. Maintain component "
            "endpoints, owned counts, and their largest-c sum from global prefix sums."
        ),
        "proof": (
            "Inside a gap-connected interval, adjacent items can be exchanged in "
            "either direction whenever ownership differs. Adjacent swaps therefore "
            "realize any ownership pattern with the same item count, including the "
            "c most expensive items. Across a gap larger than k, a trade cannot move "
            "ownership upward; it can only replace an owned higher item by a strictly "
            "cheaper lower item. Consequently ownership counts above every such gap "
            "cannot increase. The allocation taking each interval's c largest items "
            "dominates every allocation satisfying these suffix-count bounds: within "
            "each interval choose largest prices first, and any shifted ownership "
            "moves from higher prices to lower ones. Thus downward cross-gap trades "
            "cannot improve the optimum. DSU merging builds exactly these intervals "
            "and updates their independently attainable contributions."
        ),
        "time": "O((n+m) log(n+m) + q log q + (n+m) alpha(n+m))",
        "space": "O(n+m+q)",
        "invariants": [
            "For the current query every processed adjacent gap is at most k.",
            "Every DSU component is a contiguous price interval.",
            "own[root] is the initial Monocarp item count within that interval.",
            "current is the sum of the largest-own contributions of all active components.",
        ],
        "traps": [
            "An item acquired in one trade may be used to reach a further item in later trades.",
            "A gap equal to k permits an upward trade and must be merged.",
            "Queries are independent, so answers must use initial ownership counts.",
            "Total price sums require 64-bit arithmetic.",
        ],
        "edges": [
            "k=0 only merges equal prices and cannot improve the total value.",
            "A threshold joining all items gives the globally largest n prices.",
            "Duplicate prices and repeated queries are allowed.",
        ],
        "steps": [
            "Sort all item prices and identify components linked by gaps at most k.",
            "Show that adjacent feasible swaps realize arbitrary ownership within a component.",
            (
                "Prove trades across larger gaps can only move ownership downward and c"
                "annot improve the optimum."
            ),
            (
                "Compute each component's contribution as the sum of its largest initia"
                "lly-owned-count prices."
            ),
            "Sort queries, merge gaps incrementally with a DSU, and restore original query order.",
        ],
        "mutants": [
            {
                "old": "edges[next_edge].first <= k",
                "new": "edges[next_edge].first < k",
                ("claim"): (
                    "An upward trade is possible only when the price increase is stric"
                    "tly smaller than k."
                ),
                "taxonomy": "boundary_error",
            },
            {
                "old": "return prefix[right[root] + 1] - prefix[right[root] + 1 - own[root]];",
                "new": "return prefix[left[root] + own[root]] - prefix[left[root]];",
                ("claim"): (
                    "The optimal holdings within a tradable component are its cheapest c items."
                ),
                "taxonomy": "algorithm_logic",
            },
        ],
    },
}
