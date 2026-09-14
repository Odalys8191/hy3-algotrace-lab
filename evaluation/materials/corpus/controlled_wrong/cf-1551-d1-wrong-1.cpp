#include <bits/stdc++.h>
using namespace std;
using ll = long long;
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;while(t--){
 int n,m,k;cin>>n>>m>>k;bool ok=true;
 if(n%2){k-=0;n--;if(k<0)ok=false;}
 if(k%2!=0||k>n*(m/2))ok=false;
 cout<<(ok?"YES":"NO")<<'\n';}}
