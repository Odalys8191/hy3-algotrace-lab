#include <bits/stdc++.h>
using namespace std;
using ll = long long;
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;while(t--){
 int n;cin>>n;vector<ll>a(n);for(auto &x:a)cin>>x;int ans=1;
 vector<pair<ll,int>>prev;for(int i=1;i<n;i++){ll d=llabs(a[i]-a[i-1]);
 vector<pair<ll,int>>cur;cur.push_back({d,i-1});
 for(auto [g,l]:prev){ll ng=gcd(g,d);if(cur.back().first==ng)cur.back().second=min(cur.back().second,l);
 else cur.push_back({ng,l});}
 for(auto [g,l]:cur)if(g>=1)ans=max(ans,i-l+1);prev=move(cur);}
 cout<<ans<<'\n';}}
