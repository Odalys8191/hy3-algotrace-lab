#include <bits/stdc++.h>
using namespace std;
using ll = long long;
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int n;cin>>n;const ll M=998244353;
 vector<ll>x(n),pref(n+1);ll ans=0;for(int i=0;i<n;i++){ll y;int s;cin>>x[i]>>y>>s;
 int j=lower_bound(x.begin(),x.begin()+i,y)-x.begin();
 ll cost=(x[i]-y+pref[i]-pref[j]+M)%M;pref[i+1]=(pref[i]+cost)%M;
 if(s)ans=(ans+cost)%M;}cout<<(ans+x.back())%M<<'\n';}
