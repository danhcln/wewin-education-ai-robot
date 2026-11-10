/* Host-only protocol oracle. No firmware, USB, network or credential APIs.
 * Header offsets mirror pinned 78 mqtt_protocol.cc SendAudio/UDP OnMessage.
 * AES-CTR mirrors mbedTLS's per-block big-endian increment, using an independent
 * AES implementation (Windows CNG ECB), not Python/OpenSSL/WeWIN crypto.
 * Synthetic public test keys only. This is not the TanDev executable.
 */
#include <windows.h>
#include <bcrypt.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LIMIT 1291
static unsigned char key[16], iv[16], input[LIMIT], output[LIMIT];
static int nybble(char c) {
    if(c>='0'&&c<='9')return c-'0';
    if(c>='a'&&c<='f')return c-'a'+10;
    if(c>='A'&&c<='F')return c-'A'+10;
    return -1;
}
static int hex(const char *s,unsigned char *out,size_t maximum) {
    size_t size=strlen(s);
    if(size%2 || size/2>maximum)return -1;
    for(size_t i=0;i<size/2;i++) {
        int a=nybble(s[2*i]),b=nybble(s[2*i+1]);
        if(a<0||b<0)return -1;
        out[i]=(unsigned char)((a<<4)|b);
    }
    return (int)(size/2);
}
static uint32_t be32(const unsigned char *p) {
    return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];
}
static void put32(unsigned char *p,uint32_t n) {
    p[0]=n>>24;p[1]=n>>16;p[2]=n>>8;p[3]=n;
}
static int number(const char *s,uint32_t *v) {
    char *end;unsigned long long n=strtoull(s,&end,0);
    if(!*s||*end||n>UINT32_MAX)return -1;
    *v=(uint32_t)n;return 0;
}
static int ctr(const unsigned char *data,unsigned char *out,size_t size) {
    BCRYPT_ALG_HANDLE alg=NULL;BCRYPT_KEY_HANDLE handle=NULL;
    unsigned char counter[16],stream[16];ULONG written=0;
    int status=1;
    memcpy(counter,iv,16);
    if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_AES_ALGORITHM,NULL,0)<0)goto done;
    if(BCryptSetProperty(alg,BCRYPT_CHAINING_MODE,(PUCHAR)BCRYPT_CHAIN_MODE_ECB,sizeof(BCRYPT_CHAIN_MODE_ECB),0)<0)goto done;
    if(BCryptGenerateSymmetricKey(alg,&handle,NULL,0,key,16,0)<0)goto done;
    for(size_t pos=0;pos<size;pos+=16) {
        if(BCryptEncrypt(handle,counter,16,NULL,NULL,0,stream,16,&written,0)<0||written!=16)goto done;
        for(size_t j=0;j<16 && pos+j<size;j++)out[pos+j]=data[pos+j]^stream[j];
        for(int j=15;j>=0;j--)if(++counter[j]!=0)break;
    }
    status=0;
done:
    if(handle)BCryptDestroyKey(handle);
    if(alg)BCryptCloseAlgorithmProvider(alg,0);
    return status;
}
static void print_hex(const unsigned char *s,size_t n) {
    for(size_t i=0;i<n;i++)printf("%02x",s[i]);
    puts("");
}
int main(int argc,char **argv) {
    int size;uint32_t timestamp,sequence,last;
    if(argc==2&&!strcmp(argv[1],"batch")) {
        char line[4096];
        while(fgets(line,sizeof(line),stdin)) {
            char *args[9]={"oracle"};int count=1;
            char *part=strtok(line," \t\r\n");
            while(part&&count<9){args[count++]=part;part=strtok(NULL," \t\r\n");}
            int result=(part||count<2||!strcmp(args[1],"batch"))?2:main(count,args);
            if(result)printf("ERROR:%d\n",result);
            fflush(stdout);
        }
        return 0;
    }
    if(argc<5||hex(argv[2],key,16)!=16)return 2;
    if(!strcmp(argv[1],"crypt")) {
        if(argc!=5||hex(argv[3],iv,16)!=16||(size=hex(argv[4],input,LIMIT))<1)return 2;
        if(ctr(input,output,(size_t)size))return 3;
        print_hex(output,size);return 0;
    }
    if(!strcmp(argv[1],"send")) {
        if(argc!=7||hex(argv[3],iv,16)!=16||number(argv[4],&timestamp)||number(argv[5],&sequence)||
           (size=hex(argv[6],input,1275))<1)return 2;
        iv[2]=size>>8;iv[3]=size;put32(iv+8,timestamp);put32(iv+12,sequence);
        memcpy(output,iv,16);
        if(ctr(input,output+16,(size_t)size))return 3;
        print_hex(output,size+16);return 0;
    }
    if(!strcmp(argv[1],"receive")) {
        if(argc!=5||(size=hex(argv[3],input,LIMIT))<17||number(argv[4],&last))return 2;
        unsigned length=((unsigned)input[2]<<8)|input[3];
        if(input[0]!=1||length!=(unsigned)size-16||be32(input+12)<=last)return 4;
        /* Pinned receiver does not validate flags, SSRC or timestamp age. */
        memcpy(iv,input,16);
        if(ctr(input+16,output,length))return 3;
        print_hex(output,length);return 0;
    }
    return 2;
}
