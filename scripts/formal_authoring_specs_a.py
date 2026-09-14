"""Original project solutions derived from the frozen public problem statements.

No third-party solution source is used. Mutations are reproducible textual edits.
"""

HEADER = "#include <bits/stdc++.h>\nusing namespace std;\nusing ll = long long;\n"
SPECS = {}


def add(pid, body, algorithm, proof, time, space, steps, traps, mutations):
    SPECS[pid] = dict(
        code=HEADER + body.strip() + "\n",
        algorithm=algorithm,
        proof=proof,
        time=time,
        space=space,
        steps=steps,
        invariants=steps[1:3],
        traps=traps,
        edges=traps,
        mutants=[dict(old=o, new=n, claim=c, taxonomy=t) for o, n, c, t in mutations],
    )


add(
    "cf-1613-c",
    r"""
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);
 int t;cin>>t;while(t--){int n;ll h;cin>>n>>h;vector<ll>a(n);for(auto &v:a)cin>>v;
 ll lo=1,hi=h;while(lo<hi){ll k=lo+(hi-lo)/2;__int128 d=k;
 for(int i=1;i<n;i++)d+=min(k,a[i]-a[i-1]);
 if(d>=h)hi=k;else lo=k+1;}cout<<lo<<'\n';}}
""",
    (
        "Damage is k plus the sum of min(k, adjacent attack gap); binary search"
        " its first feasible k."
    ),
    (
        "Each attack contributes until the next attack or poison expiry; the la"
        "st contributes k. The sum is monotone, and k=h is feasible, so lower-b"
        "ound search returns the minimum."
    ),
    "O(n log h)",
    "O(n)",
    [
        "Poison refresh replaces the previous effect.",
        "Nonfinal damage is min(k, next gap).",
        "The last attack contributes k.",
        "Damage is monotone in k; binary search the first feasible integer.",
        "Accumulate in a wider integer to avoid overflow.",
    ],
    ["Single attack", "Overlapping poison intervals", "Health up to 10^18"],
    [
        ("d=k;", "d=0;", "The last attack contributes no damage.", "algorithm_logic"),
        (
            "if(d>=h)",
            "if(d>h)",
            "Exactly h damage is insufficient to kill the dragon.",
            "boundary_error",
        ),
    ],
)

add(
    "cf-1617-c",
    r"""
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;while(t--){
 int n;cin>>n;vector<int>used(n+1);vector<ll>extra;for(int i=0;i<n;i++){ll x;cin>>x;
 if(x<=n&&!used[x])used[x]=1;else extra.push_back(x);}
 vector<ll>missing;for(int x=1;x<=n;x++)if(!used[x])missing.push_back(x);
 sort(extra.begin(),extra.end());bool ok=true;for(int i=0;i<(int)extra.size();i++)
 if(extra[i]<=2*missing[i])ok=false;
 cout<<(ok?(int)extra.size():-1)<<'\n';}}
""",
    (
        "Keep one occurrence of each value in [1,n], sort surplus values and mi"
        "ssing targets, then match in increasing order."
    ),
    (
        "A changed positive value v can produce target r iff v>2r: choose modul"
        "us v-r. Keeping an existing valid value never hurts, and monotone feas"
        "ible intervals justify ordered matching."
    ),
    "O(n log n)",
    "O(n)",
    [
        "Keep one copy of each valid permutation value.",
        "A genuine modulo reduction to r needs v>2r.",
        "Sorted surplus-to-missing matching preserves all larger feasible choices.",
        (
            "Every surplus requires exactly one operation; a failed match makes con"
            "struction impossible."
        ),
    ],
    ["Duplicate small values", "Equality v=2r is infeasible", "Already a permutation"],
    [
        (
            "extra[i]<=2*missing[i]",
            "extra[i]<2*missing[i]",
            "Modulo can reduce 2r to r.",
            "boundary_error",
        ),
        (
            "sort(extra.begin(),extra.end());",
            "sort(extra.rbegin(),extra.rend());",
            "Largest surplus should be paired with smallest missing target.",
            "algorithm_logic",
        ),
    ],
)

add(
    "cf-1549-d",
    (
        "\n"
        "int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;w"
        "hile(t--){\n"
        " int n;cin>>n;vector<ll>a(n);for(auto &x:a)cin>>x;int ans=1;\n"
        " vector<pair<ll,int>>prev;for(int i=1;i<n;i++){ll d=llabs(a[i]-a[i-1])"
        ";\n"
        " vector<pair<ll,int>>cur;cur.push_back({d,i-1});\n"
        " for(auto [g,l]:prev){ll ng=gcd(g,d);if(cur.back().first==ng)cur.back("
        ").second=min(cur.back().second,l);\n"
        " else cur.push_back({ng,l});}\n"
        " for(auto [g,l]:cur)if(g>1)ans=max(ans,i-l+1);prev=move(cur);}\n"
        " cout<<ans<<'\\n';}}\n"
    ),
    (
        "Compress the distinct GCD values of adjacent-difference suffixes, keep"
        "ing the earliest start for each."
    ),
    (
        "Equal residues modulo m are equivalent to m dividing every adjacent di"
        "fference. Thus a nontrivial subarray is valid exactly when its differe"
        "nce GCD exceeds one. Extending all suffix GCD states enumerates every "
        "candidate, and equal GCD states may keep only their earliest start."
    ),
    "O(n log V)",
    "O(n + log V)",
    [
        "Convert congruence equality into divisibility of adjacent differences.",
        "A common modulus at least two exists iff GCD>1.",
        "Each suffix state retains its earliest possible start.",
        "Extending and merging GCD states covers all subarrays.",
        "A single element always forms a friend group.",
    ],
    ["n=1", "Difference equal to 1", "64-bit input differences"],
    [
        (
            "if(g>1)",
            "if(g>=1)",
            "GCD one permits a common modulus at least two.",
            "algorithm_logic",
        ),
        (
            "i-l+1",
            "i-l",
            "The number of differences equals the number of array elements.",
            "boundary_error",
        ),
    ],
)

add(
    "cf-1622-c",
    r"""
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;while(t--){
 int n;ll k;cin>>n>>k;vector<ll>a(n);ll sum=0;for(auto &x:a){cin>>x;sum+=x;}
 sort(a.begin(),a.end());ll ans=max(0LL,sum-k),suffix=0;
 for(int c=0;c<n;c++){if(c)suffix+=a[n-c];ll remaining=sum-suffix-a[0];
 ll deficit=remaining+(c+1)*a[0]-k;ll dec=deficit>0?(deficit+c)/(c+1):0;
 ans=min(ans,c+dec);}cout<<ans<<'\n';}}
""",
    (
        "Enumerate how many largest elements are assigned to a possibly decreas"
        "ed minimum; derive the required decreases by ceiling division."
    ),
    (
        "For a fixed number c of assignments, replacing the c largest values by"
        " the eventual minimum maximizes reduction. Decreasing that common sour"
        "ce first reduces c+1 values per decrease. All other changes can be con"
        "solidated into this form without more operations."
    ),
    "O(n log n)",
    "O(n)",
    [
        "Sort values and choose the minimum as the common assignment source.",
        "For c assignments, choose the c largest targets.",
        "Each decrease of the source saves c+1 in the eventual sum.",
        "Ceiling-divide the remaining positive deficit.",
        "Minimize c plus decreases over 0 through n-1.",
    ],
    ["Sum already within bound", "Negative eventual minimum is allowed", "n=1"],
    [
        (
            "(deficit+c)/(c+1)",
            "deficit/(c+1)",
            "Rounding down the decreases always meets the target sum.",
            "boundary_error",
        ),
        (
            "suffix+=a[n-c]",
            "suffix+=a[c-1]",
            "Replacing the smallest targets maximizes sum reduction.",
            "algorithm_logic",
        ),
    ],
)

add(
    "cf-1551-e",
    r"""
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;while(t--){
 int n,k;cin>>n>>k;vector<int>a(n);for(auto &x:a)cin>>x;
 vector<int>dp(n+1,-1000000);dp[0]=0;for(int i=1;i<=n;i++){
 vector<int>ndp(n+1,-1000000);for(int d=0;d<i;d++)if(dp[d]>=0){
 ndp[d]=max(ndp[d],dp[d]+(a[i-1]==i-d));
 ndp[d+1]=max(ndp[d+1],dp[d]);}dp.swap(ndp);}
 int ans=-1;for(int d=0;d<=n;d++)if(dp[d]>=k){ans=d;break;}cout<<ans<<'\n';}}
""",
    (
        "Dynamic programming over prefix length and deletion count stores the m"
        "aximum number of fixed points."
    ),
    (
        "With i processed values and d deletions, retaining a_i places it at in"
        "dex i-d; deleting it keeps the number of matches unchanged. These are "
        "exhaustive disjoint choices. The least feasible deletion state is opti"
        "mal."
    ),
    "O(n^2)",
    "O(n)",
    [
        "Process the original values in order.",
        "The DP value is the maximum fixed-point count for each deletion count.",
        "Keeping the current value puts it at position i-d.",
        "Deleting moves to state d+1 without a new match.",
        "Return the smallest deletion count with at least k matches.",
    ],
    ["Impossible k", "Zero deletions already sufficient", "Indices shift after deletion"],
    [
        (
            "a[i-1]==i-d",
            "a[i-1]==i",
            "Deleted elements do not change later indices.",
            "problem_misread",
        ),
        (
            "if(dp[d]>=k)",
            "if(dp[d]>k)",
            "Exactly k fixed points are insufficient.",
            "boundary_error",
        ),
    ],
)

add(
    "cf-1552-f",
    r"""
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int n;cin>>n;const ll M=998244353;
 vector<ll>x(n),pref(n+1);ll ans=0;for(int i=0;i<n;i++){ll y;int s;cin>>x[i]>>y>>s;
 int j=lower_bound(x.begin(),x.begin()+i,y)-x.begin();
 ll cost=(x[i]-y+pref[i]-pref[j]+M)%M;pref[i+1]=(pref[i]+cost)%M;
 if(s)ans=(ans+cost)%M;}cout<<(ans+x.back()+1)%M<<'\n';}
""",
    (
        "For each portal, compute the extra round-trip time from its destinatio"
        "n using prefix sums of earlier detour costs and a lower bound."
    ),
    (
        "After the ant first passes an earlier portal it is active. A later bac"
        "kward detour triggers each earlier portal in its interval, adding that"
        " portal's own restoration detour. Prefix sums yield this cost; initial"
        "ly active portals add their cost to the straight-line journey."
    ),
    "O(n log n)",
    "O(n)",
    [
        "Start with the straight-line distance x_n+1.",
        "A portal detour contains x_i-y_i walking plus earlier restoration detours.",
        "The earlier affected portals start at lower_bound(y_i).",
        "Prefix sums compute their total modulo 998244353.",
        "Only initially active portals add a detour to the initial journey.",
    ],
    ["All portals inactive", "Destination left of every earlier portal", "Modulo subtraction"],
    [
        (
            "if(s)ans=",
            "if(!s)ans=",
            "Initially inactive portals immediately teleport the ant.",
            "problem_misread",
        ),
        (
            "x.back()+1",
            "x.back()",
            "The journey ends at the last portal position.",
            "boundary_error",
        ),
    ],
)

add(
    "cf-1556-b",
    r"""
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;while(t--){
 int n;cin>>n;vector<int>odd;for(int i=0;i<n;i++){ll a;cin>>a;if(a%2)odd.push_back(i);}
 ll ans=LLONG_MAX;for(int start=0;start<2;start++){
 int need=(n+1-start)/2;if((int)odd.size()!=need)continue;ll cost=0;
 for(int i=0;i<need;i++)cost+=llabs(odd[i]-(start+2*i));ans=min(ans,cost);}
 cout<<(ans==LLONG_MAX?-1:ans)<<'\n';}}
""",
    (
        "Try the two alternating parity layouts and sum distances between order"
        "ed odd positions and their target positions."
    ),
    (
        "Order within one parity never needs to change. Each adjacent swap cros"
        "sing parities moves exactly one odd item one step, so the sum of order"
        "ed distances is both a lower bound and attainable. Only layouts with t"
        "he correct parity counts are feasible."
    ),
    "O(n)",
    "O(n)",
    [
        "An alternating array has one of two possible starting parities.",
        "Feasibility is determined by parity counts.",
        "Match odd positions to odd targets in their existing order.",
        "Sum absolute movements to count swaps without double counting.",
        "Take the smaller feasible layout cost.",
    ],
    ["Unbalanced parity counts", "Two feasible layouts for even length", "Already alternating"],
    [
        (
            "cost+=llabs(odd[i]-(start+2*i))",
            "cost+=(odd[i]!=(start+2*i))",
            "Each misplaced odd item needs only one adjacent swap regardless of distance.",
            "algorithm_logic",
        ),
        (
            "start<2",
            "start<1",
            "Only layouts starting with an odd value need consideration.",
            "constraint_omission",
        ),
    ],
)

add(
    "cf-1579-c",
    (
        "\n"
        "int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;w"
        "hile(t--){\n"
        " int n,m,k;cin>>n>>m>>k;vector<string>a(n);for(auto &s:a)cin>>s;\n"
        " vector<vector<int>>cover(n,vector<int>(m));for(int i=0;i<n;i++)for(in"
        "t j=0;j<m;j++)if(a[i][j]=='*'){\n"
        " int d=0;while(i-d-1>=0&&j-d-1>=0&&j+d+1<m&&a[i-d-1][j-d-1]=='*'&&a[i-"
        "d-1][j+d+1]=='*')d++;\n"
        " if(d>=k)for(int h=0;h<=d;h++)cover[i-h][j-h]=cover[i-h][j+h]=1;}\n"
        " bool ok=true;for(int i=0;i<n;i++)for(int j=0;j<m;j++)if(a[i][j]=='*'&"
        "&!cover[i][j])ok=false;\n"
        ' cout<<(ok?"YES":"NO")<<\'\\n\';}}\n'
    ),
    (
        "Enumerate each possible tick center, find its longest complete pair of"
        " arms, and mark every cell covered by a valid tick."
    ),
    (
        "Every tick marked by the algorithm paints only existing stars and meet"
        "s the size bound. Any feasible drawing uses ticks contained in these m"
        "aximal ticks, so every star must be covered by the union. Thus coverag"
        "e is necessary and sufficient."
    ),
    "O(n m min(n,m))",
    "O(n m)",
    [
        "A candidate center must be a star.",
        "Grow both upward diagonal arms together until either arm stops.",
        "A maximal tick of size at least k covers all its own smaller valid ticks.",
        "Mark the union of all valid ticks.",
        "Accept exactly when every star is covered.",
    ],
    ["Empty grid", "A tick of size exactly k", "An isolated star"],
    [
        ("if(d>=k)", "if(d>k)", "A tick with arm length exactly k is invalid.", "boundary_error"),
        ("h<=d", "h<d", "The top endpoint of each tick need not be marked.", "boundary_error"),
    ],
)

add(
    "cf-1551-d1",
    r"""
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;while(t--){
 int n,m,k;cin>>n>>m>>k;bool ok=true;
 if(n%2){k-=m/2;n--;if(k<0)ok=false;}
 if(k%2!=0||k>n*(m/2))ok=false;
 cout<<(ok?"YES":"NO")<<'\n';}}
""",
    (
        "Remove a forced horizontal row when n is odd, then check that the rema"
        "ining horizontal count is even and within the paired-column capacity."
    ),
    (
        "An odd-height board has an odd number of cells in each column, forcing"
        " at least m/2 horizontal dominoes with the same parity as that row. Af"
        "ter it is removed, 2x2 blocks contribute either zero or two horizontal"
        "s, and a possible odd final column is vertical. These bounds and parit"
        "y conditions also give a construction."
    ),
    "O(1) per case",
    "O(1)",
    [
        "If n is odd, allocate m/2 horizontal dominoes to one row.",
        "The remaining height is even.",
        "Every 2x2 block contributes zero or two horizontal dominoes.",
        "An odd final column can be filled vertically.",
        "Check remaining nonnegative count, even parity, and capacity.",
    ],
    ["Single row", "Single column", "Odd remaining horizontal count"],
    [
        ("k-=m/2", "k-=0", "An odd row does not consume horizontal dominoes.", "algorithm_logic"),
        (
            "k%2!=0||k>n*(m/2)",
            "k>n*(m/2)",
            "Every count within capacity is tileable regardless of parity.",
            "constraint_omission",
        ),
    ],
)

add(
    "cf-1556-c",
    (
        "\n"
        "int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int n;cin>>n;v"
        "ector<ll>c(n);for(auto &v:c)cin>>v;\n"
        " ll ans=0;for(int i=0;i<n;i+=2){ll b=0,mn=0;for(int j=i+1;j<n;j++){\n"
        " if(j%2){ll lo=max({1LL,1-b,-mn});ll hi=min(c[i],c[j]-b);if(hi>=lo)ans"
        "+=hi-lo+1;}\n"
        " b+=(j%2?-c[j]:c[j]);mn=min(mn,b);}}\n"
        " cout<<ans<<'\\n';}\n"
    ),
    (
        "Enumerate the opening run and closing run; count possible starting suf"
        "fix lengths using net balance and the minimum intermediate prefix bala"
        "nce."
    ),
    (
        "A substring starts in an opening run and ends in a closing run. If x o"
        "pening brackets are selected and the full intermediate balance is b, t"
        "he final selected closing count is x+b. The constraints x>=1, x+b>=1, "
        "x<=c_i, x+b<=c_j, and x+minimum_prefix>=0 define exactly an integer in"
        "terval."
    ),
    "O(n^2)",
    "O(n)",
    [
        (
            "A nonempty regular sequence starts with an opening bracket and ends wi"
            "th a closing bracket."
        ),
        "For fixed endpoint runs, choose a suffix of x openings.",
        "The final closing prefix must have length x+b.",
        "Intermediate balance never falls below zero iff x is at least minus the minimum prefix.",
        "Intersect these bounds and count integer x values.",
    ],
    ["One run only", "Adjacent endpoint runs", "A deep intermediate negative prefix"],
    [
        (
            "max({1LL,1-b,-mn})",
            "max(1LL,1-b)",
            "Only total balance matters; intermediate negative balance is harmless.",
            "algorithm_logic",
        ),
        (
            "ans+=hi-lo+1",
            "ans+=hi-lo",
            "The number of integers in an inclusive interval is its endpoint difference.",
            "boundary_error",
        ),
    ],
)

add(
    "cf-1575-k",
    (
        "\n"
        "int main(){ios::sync_with_stdio(false);cin.tie(nullptr);ll n,m,k,r,c,a"
        "x,ay,bx,by;cin>>n>>m>>k>>r>>c>>ax>>ay>>bx>>by;\n"
        " ll e=n*m;if(ax!=bx||ay!=by)e-=r*c;const ll M=1000000007;ll ans=1;\n"
        " for(;e;e/=2,k=k*k%M)if(e%2)ans=ans*k%M;cout<<ans<<'\\n';}\n"
    ),
    (
        "Treat corresponding cells as equality edges. Distinct translated recta"
        "ngles impose r*c independent equalities, so exponentiate k to n*m-r*c;"
        " identical rectangles impose none."
    ),
    (
        "For a nonzero displacement, every equality edge advances by the same v"
        "ector. Each vertex has at most one incoming and outgoing edge, and pro"
        "jection along the vector rules out cycles. The equality graph is a for"
        "est, so each of its r*c distinct edges reduces the number of independe"
        "nt colors by one."
    ),
    "O(log(n m))",
    "O(1)",
    [
        "Associate each corresponding-cell equality with one edge.",
        "A nonzero translation produces directed paths and no cycles.",
        "Every edge reduces the number of connected components by one.",
        "Identical rectangles impose no restriction.",
        "Each component chooses one of k colors; modular exponentiation counts assignments.",
    ],
    ["Identical rectangles", "Overlapping translated rectangles", "Grid area up to 10^18"],
    [
        (
            "if(ax!=bx||ay!=by)",
            "if(true)",
            "Even identical rectangles impose r*c independent equalities.",
            "algorithm_logic",
        ),
        (
            "ax!=bx||ay!=by",
            "ax!=bx&&ay!=by",
            "A displacement along only one coordinate imposes no equalities.",
            "algorithm_logic",
        ),
    ],
)

add(
    "cf-1618-f",
    (
        "\n"
        "string bits(ll x){string s;while(x){s+=char('0'+x%2);x/=2;}reverse(s.b"
        "egin(),s.end());return s;}\n"
        "int main(){ios::sync_with_stdio(false);cin.tie(nullptr);ll x,y;cin>>x>"
        ">y;string a=bits(x),b=bits(y);\n"
        " queue<string>q;unordered_set<string>seen;seen.insert(a);q.push(a);boo"
        "l ok=false;\n"
        " while(!q.empty()){string s=q.front();q.pop();if(s==b){ok=true;break;}"
        "\n"
        " for(char c: {'0','1'}){string v=s+c;reverse(v.begin(),v.end());v.eras"
        "e(0,v.find_first_not_of('0'));\n"
        " if(v.size()<=b.size()&&seen.insert(v).second)q.push(v);}}\n"
        ' cout<<(ok?"YES":"NO")<<\'\\n\';}\n'
    ),
    (
        "Breadth-first search the reachable canonical binary strings, pruning s"
        "uccessors longer than the target."
    ),
    (
        "After the first operation every state ends in one. Subsequent zero-app"
        "ends only reverse it, and one-appends add one at an end after reversal"
        "; lengths can no longer shrink. The original state is always expanded "
        "even if it is longer, allowing its trailing zeros to be removed. Thus "
        "pruning successors above the target length is safe and the finite sear"
        "ch is exhaustive."
    ),
    "O(L^3) with L the maximum binary length",
    "O(L^3)",
    [
        "Represent both positive integers as canonical binary strings.",
        "Generate append-zero and append-one followed by reverse and leading-zero removal.",
        "Every generated state is odd, so future transitions cannot shorten it.",
        "Prune generated states longer than the target and deduplicate them.",
        "Test the initial state as well, allowing zero operations.",
    ],
    ["x equals y", "Initial trailing zeros may disappear", "Even target differs from x"],
    [
        (
            "for(char c: {'0','1'})",
            "for(char c: {'1'})",
            "Only appending one is needed to explore reachability.",
            "constraint_omission",
        ),
        (
            "v.size()<=b.size()",
            "v.size()<b.size()",
            "A state as long as the target should be pruned.",
            "boundary_error",
        ),
    ],
)

add(
    "cf-1553-b",
    (
        "\n"
        "int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int q;cin>>q;w"
        "hile(q--){string s,t;cin>>s>>t;\n"
        " int n=s.size(),m=t.size();vector<char>right(n),left(n);for(int i=0;i<"
        "n;i++)right[i]=(s[i]==t[0]);\n"
        " for(int p=1;p<m;p++){vector<char>nr(n),nl(n);for(int i=0;i<n;i++)if(s"
        "[i]==t[p]){\n"
        " if(i>0)nr[i]=right[i-1];if(i+1<n)nl[i]=left[i+1]||right[i+1];}\n"
        " right.swap(nr);left.swap(nl);}\n"
        " bool ok=false;for(int i=0;i<n;i++)ok=ok||right[i]||left[i];cout<<(ok?"
        '"Yes":"No")<<\'\\n\';}}\n'
    ),
    (
        "Use two reachability states per source position: still moving right, o"
        "r already moving left."
    ),
    (
        "Initialization allows any matching starting character. Each next targe"
        "t character moves a right-state one step right, or either state one st"
        "ep left into the permanent left phase. These transitions represent exa"
        "ctly paths with at most one right-to-left turn."
    ),
    "O(|s| |t|)",
    "O(|s|)",
    [
        "Allow every matching starting position.",
        "Track separately positions before and after the direction change.",
        "A right move is available only before the turn.",
        "A left move can begin or continue the left phase.",
        "Any reachable position after consuming the target proves feasibility.",
    ],
    ["Target length one", "Turning immediately", "Turning back to the right is forbidden"],
    [
        (
            "left[i+1]||right[i+1]",
            "left[i+1]",
            "The chip may never switch from right movement to left movement.",
            "constraint_omission",
        ),
        (
            "right[i-1]",
            "(right[i-1]||left[i-1])",
            "After moving left the chip may switch back to moving right.",
            "problem_misread",
        ),
    ],
)

add(
    "cf-1598-c",
    (
        "\n"
        "int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;w"
        "hile(t--){int n;cin>>n;vector<ll>a(n);ll sum=0;\n"
        " for(auto &v:a){cin>>v;sum+=v;}if((2*sum)%n){cout<<0<<'\\n';continue;}\n"
        " ll target=2*sum/n,ans=0;map<ll,ll>seen;for(ll x:a){ans+=seen[target-x"
        "];seen[x]++;}cout<<ans<<'\\n';}}\n"
    ),
    (
        "Convert preservation of the mean into a pair-sum equation and count co"
        "mplements among previously seen values."
    ),
    (
        "The equality (S-a_i-a_j)/(n-2)=S/n is equivalent to a_i+a_j=2S/n. If t"
        "he right side is nonintegral no pair works. Adding counts of prior com"
        "plements counts each unordered pair exactly once."
    ),
    "O(n log n)",
    "O(n)",
    [
        "Let S denote the original sum.",
        "Equal means require the removed pair sum to equal 2S/n.",
        "Reject a nonintegral target using exact arithmetic.",
        "Count complements among earlier positions only.",
        "Accumulate the number of pairs in 64 bits.",
    ],
    ["All values equal", "Nonintegral twice-mean", "Duplicate complements"],
    [
        (
            "ans+=seen[target-x];seen[x]++;",
            "seen[x]++;ans+=seen[target-x];",
            "A position may pair with itself.",
            "boundary_error",
        ),
        (
            "ll target=2*sum/n",
            "ll target=sum/n",
            "The removed pair sum must equal one copy of the original mean.",
            "algorithm_logic",
        ),
    ],
)

add(
    "cf-1620-d",
    (
        "\n"
        "int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;w"
        "hile(t--){int n;cin>>n;vector<ll>a(n);for(auto &x:a)cin>>x;\n"
        " ll ans=LLONG_MAX;for(int one=0;one<=2;one++)for(int two=0;two<=2;two+"
        "+){\n"
        " ll need=0;bool ok=true;for(ll x:a){ll best=LLONG_MAX;for(int u=0;u<=o"
        "ne;u++)for(int v=0;v<=two;v++){\n"
        " ll rem=x-u-2*v;if(rem>=0&&rem%3==0)best=min(best,rem/3);}\n"
        " if(best==LLONG_MAX){ok=false;break;}need=max(need,best);}if(ok)ans=mi"
        "n(ans,one+two+need);}\n"
        " cout<<ans<<'\\n';}}\n"
    ),
    (
        "Enumerate zero to two coins of each small denomination and derive the "
        "minimum number of threes needed to represent every price."
    ),
    (
        "Three or more ones can be replaced by fewer coins of denominations one"
        " and two without losing any subset sum; three twos can be replaced by "
        "one two, one one and one three while preserving their subset sums and "
        "coin count, and further normalized. Therefore an optimum exists with a"
        "t most two ones and two twos. For each such choice enumerate their usa"
        "ge and maximize the per-price minimum count of threes."
    ),
    "O(n)",
    "O(n)",
    [
        "Normalize the inventory to at most two coins of each small denomination.",
        "Enumerate the small-coin inventory.",
        "For each price enumerate all available small-coin subsets.",
        "A nonnegative remainder divisible by three determines the needed threes.",
        "The maximum per-price need suffices because only one flavor is purchased.",
    ],
    ["Price one or two", "Different residues modulo three", "Large prices"],
    [
        (
            "need=max(need,best)",
            "need=min(need,best)",
            "The smallest per-flavor demand is enough for every flavor.",
            "algorithm_logic",
        ),
        (
            "rem>=0&&rem%3==0",
            "rem>=0",
            "Every nonnegative remainder can be paid by rounding its number of threes down.",
            "constraint_omission",
        ),
    ],
)
