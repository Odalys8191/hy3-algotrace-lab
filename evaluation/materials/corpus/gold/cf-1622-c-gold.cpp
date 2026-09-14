#include <bits/stdc++.h>
using namespace std;
using ll = long long;
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;while(t--){
 int n;ll k;cin>>n>>k;vector<ll>a(n);ll sum=0;for(auto &x:a){cin>>x;sum+=x;}
 sort(a.begin(),a.end());ll ans=max(0LL,sum-k),suffix=0;
 for(int c=0;c<n;c++){if(c)suffix+=a[n-c];ll remaining=sum-suffix-a[0];
 ll deficit=remaining+(c+1)*a[0]-k;ll dec=deficit>0?(deficit+c)/(c+1):0;
 ans=min(ans,c+dec);}cout<<ans<<'\n';}}
