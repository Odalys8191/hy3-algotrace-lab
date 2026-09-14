#include <bits/stdc++.h>
using namespace std;
using ll = long long;
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int n;cin>>n;vector<ll>c(n);for(auto &v:c)cin>>v;
 ll ans=0;for(int i=0;i<n;i+=2){ll b=0,mn=0;for(int j=i+1;j<n;j++){
 if(j%2){ll lo=max({1LL,1-b,-mn});ll hi=min(c[i],c[j]-b);if(hi>=lo)ans+=hi-lo;}
 b+=(j%2?-c[j]:c[j]);mn=min(mn,b);}}
 cout<<ans<<'\n';}
