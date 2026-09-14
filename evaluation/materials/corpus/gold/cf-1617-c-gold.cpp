#include <bits/stdc++.h>
using namespace std;
using ll = long long;
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;while(t--){
 int n;cin>>n;vector<int>used(n+1);vector<ll>extra;for(int i=0;i<n;i++){ll x;cin>>x;
 if(x<=n&&!used[x])used[x]=1;else extra.push_back(x);}
 vector<ll>missing;for(int x=1;x<=n;x++)if(!used[x])missing.push_back(x);
 sort(extra.begin(),extra.end());bool ok=true;for(int i=0;i<(int)extra.size();i++)
 if(extra[i]<=2*missing[i])ok=false;
 cout<<(ok?(int)extra.size():-1)<<'\n';}}
