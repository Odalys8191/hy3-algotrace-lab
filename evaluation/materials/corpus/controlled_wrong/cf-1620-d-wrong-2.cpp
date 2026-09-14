#include <bits/stdc++.h>
using namespace std;
using ll = long long;
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;while(t--){int n;cin>>n;vector<ll>a(n);for(auto &x:a)cin>>x;
 ll ans=LLONG_MAX;for(int one=0;one<=2;one++)for(int two=0;two<=2;two++){
 ll need=0;bool ok=true;for(ll x:a){ll best=LLONG_MAX;for(int u=0;u<=one;u++)for(int v=0;v<=two;v++){
 ll rem=x-u-2*v;if(rem>=0)best=min(best,rem/3);}
 if(best==LLONG_MAX){ok=false;break;}need=max(need,best);}if(ok)ans=min(ans,one+two+need);}
 cout<<ans<<'\n';}}
