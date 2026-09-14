#include <bits/stdc++.h>
using namespace std;
using ll = long long;
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);
 int t;cin>>t;while(t--){int n;ll h;cin>>n>>h;vector<ll>a(n);for(auto &v:a)cin>>v;
 ll lo=1,hi=h;while(lo<hi){ll k=lo+(hi-lo)/2;__int128 d=0;
 for(int i=1;i<n;i++)d+=min(k,a[i]-a[i-1]);
 if(d>=h)hi=k;else lo=k+1;}cout<<lo<<'\n';}}
