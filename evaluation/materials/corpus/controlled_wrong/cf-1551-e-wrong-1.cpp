#include <bits/stdc++.h>
using namespace std;
using ll = long long;
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;while(t--){
 int n,k;cin>>n>>k;vector<int>a(n);for(auto &x:a)cin>>x;
 vector<int>dp(n+1,-1000000);dp[0]=0;for(int i=1;i<=n;i++){
 vector<int>ndp(n+1,-1000000);for(int d=0;d<i;d++)if(dp[d]>=0){
 ndp[d]=max(ndp[d],dp[d]+(a[i-1]==i));
 ndp[d+1]=max(ndp[d+1],dp[d]);}dp.swap(ndp);}
 int ans=-1;for(int d=0;d<=n;d++)if(dp[d]>=k){ans=d;break;}cout<<ans<<'\n';}}
