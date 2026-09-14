#include <bits/stdc++.h>
using namespace std;
using ll = long long;
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;while(t--){
 int n,m,k;cin>>n>>m>>k;vector<string>a(n);for(auto &s:a)cin>>s;
 vector<vector<int>>cover(n,vector<int>(m));for(int i=0;i<n;i++)for(int j=0;j<m;j++)if(a[i][j]=='*'){
 int d=0;while(i-d-1>=0&&j-d-1>=0&&j+d+1<m&&a[i-d-1][j-d-1]=='*'&&a[i-d-1][j+d+1]=='*')d++;
 if(d>=k)for(int h=0;h<=d;h++)cover[i-h][j-h]=cover[i-h][j+h]=1;}
 bool ok=true;for(int i=0;i<n;i++)for(int j=0;j<m;j++)if(a[i][j]=='*'&&!cover[i][j])ok=false;
 cout<<(ok?"YES":"NO")<<'\n';}}
