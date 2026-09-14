#include <bits/stdc++.h>
using namespace std;
using ll = long long;
int main(){ios::sync_with_stdio(false);cin.tie(nullptr);int q;cin>>q;while(q--){string s,t;cin>>s>>t;
 int n=s.size(),m=t.size();vector<char>right(n),left(n);for(int i=0;i<n;i++)right[i]=(s[i]==t[0]);
 for(int p=1;p<m;p++){vector<char>nr(n),nl(n);for(int i=0;i<n;i++)if(s[i]==t[p]){
 if(i>0)nr[i]=right[i-1];if(i+1<n)nl[i]=left[i+1]||right[i+1];}
 right.swap(nr);left.swap(nl);}
 bool ok=false;for(int i=0;i<n;i++)ok=ok||right[i]||left[i];cout<<(ok?"Yes":"No")<<'\n';}}
