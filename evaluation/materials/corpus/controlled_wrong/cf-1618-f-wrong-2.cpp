#include <bits/stdc++.h>
using namespace std;
using ll = long long;
string bits(ll x){string s;while(x){s+=char('0'+x%2);x/=2;}reverse(s.begin(),s.end());return s;}
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);ll x,y;cin>>x>>y;string a=bits(x),b=bits(y);
 queue<string>q;unordered_set<string>seen;seen.insert(a);q.push(a);bool ok=false;
 while(!q.empty()){string s=q.front();q.pop();if(s==b){ok=true;break;}
 for(char c: {'0','1'}){string v=s+c;reverse(v.begin(),v.end());v.erase(0,v.find_first_not_of('0'));
 if(v.size()<b.size()&&seen.insert(v).second)q.push(v);}}
 cout<<(ok?"YES":"NO")<<'\n';}
