#include <bits/stdc++.h>
using namespace std;
using ll = long long;
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int t;cin>>t;while(t--){
 int n;cin>>n;vector<int>odd;for(int i=0;i<n;i++){ll a;cin>>a;if(a%2)odd.push_back(i);}
 ll ans=LLONG_MAX;for(int start=0;start<1;start++){
 int need=(n+1-start)/2;if((int)odd.size()!=need)continue;ll cost=0;
 for(int i=0;i<need;i++)cost+=llabs(odd[i]-(start+2*i));ans=min(ans,cost);}
 cout<<(ans==LLONG_MAX?-1:ans)<<'\n';}}
