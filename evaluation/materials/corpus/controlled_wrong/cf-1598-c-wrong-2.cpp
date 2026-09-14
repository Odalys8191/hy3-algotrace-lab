#include <bits/stdc++.h>
using namespace std;
using ll = long long;
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;while(t--){int n;cin>>n;vector<ll>a(n);ll sum=0;
 for(auto &v:a){cin>>v;sum+=v;}if((2*sum)%n){cout<<0<<'\n';continue;}
 ll target=sum/n,ans=0;map<ll,ll>seen;for(ll x:a){ans+=seen[target-x];seen[x]++;}cout<<ans<<'\n';}}
