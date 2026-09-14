#include <bits/stdc++.h>
using namespace std;
using ll = long long;
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);ll n,m,k,r,c,ax,ay,bx,by;cin>>n>>m>>k>>r>>c>>ax>>ay>>bx>>by;
 ll e=n*m;if(ax!=bx&&ay!=by)e-=r*c;const ll M=1000000007;ll ans=1;
 for(;e;e/=2,k=k*k%M)if(e%2)ans=ans*k%M;cout<<ans<<'\n';}
