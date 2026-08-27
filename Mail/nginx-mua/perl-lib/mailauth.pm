package mailauth;
use nginx;
use Env;
#use DBI;
#my $dsn="DBI:mysql:database=DBNAME;host=HOSTNAME";
#our $dbh=DBI->connect_cached($dsn, 'dbusername', 'dbpass', {AutoCommit => 1});
#our $sth=$dbh->prepare("select password,mail_server from mailaccounts where username=? limit 1");
use Sys::Syslog qw(:standard :macros setlogsock);  # standard functions & macros
#use Data::Dumper;
use Net::POP3;
use Env;

my $mapFile="/etc/nginx/perl/lib/dom2srv.txt";
my $envFile="/usr/local/etc/environment";



my $ENV={};
open(FD,"<",$envFile);
while(<FD>) {
    chomp;
    ($key,$value)=split(/=/);
    $ENV{$key}=$value;
    }
close(FD);

my $sysHost=$ENV{'SYSLOG_SERVER'};
my $sysPort=$ENV{'SYSLOG_PORT'};
my $sysProto=$ENV{'SYSLOG_PROTO'};
my $sysDaem=$ENV{'SITE'};
my $trackerF2b=$ENV{'TRACKER_F2B'};
my $trackerLog=$ENV{'TRACKER_LOG'};


# https://www.nginx.com/resources/wiki/start/topics/examples/imapauthenticatewithapacheperlscript/
# http://nginx.org/en/docs/mail/ngx_mail_auth_http_module.html
# password = URLDecoder.decode(password.replaceAll("\\+", "%2b"), "UTF-8");

our $auth_ok;

sub handler {
  my $r = shift;

  openlog($sysDaem." ==".$r->header_in('Auth-Protocol')."/".$r->header_in('Auth-User')."== ", 'noeol,nonul');
  setlogsock({ type => $sysProto, host => $sysHost, port => $sysPort });

  $auth_ok=1;

  #$sth->execute($r->header_in("Auth-User"));
  #my $hash=$sth->fetchrow_hashref();
  # assuming that the query results password and mail_server
  # assuming that the password is in crypt format

  my $headers = $r;

#http://nginx.org/en/docs/mail/ngx_mail_auth_http_module.html
#Request:
#    GET /auth HTTP/1.0
#    Host: localhost
#    Auth-Method: plain # plain/apop/cram-md5/external
#    Auth-User: user
#    Auth-Pass: password
#    Auth-Protocol: imap # imap/pop3/smtp
#    Auth-Login-Attempt: 1
#    Client-IP: 192.0.2.42
#    Client-Host: client.example.org
#Good response:
#    HTTP/1.0 200 OK
#    Auth-Status: OK
#    Auth-Server: 198.51.100.1
#    Auth-Port: 143
#Bad response:
#    HTTP/1.0 200 OK
#    Auth-Status: Invalid login or password
#    Auth-Wait: 3



  syslog('info', join(':',$trackerF2b."-In",
        $r->header_in('Host'),
        $r->header_in('Auth-Method'),
        $r->header_in('Auth-User'),
#        $r->header_in('Auth-Pass'),
        $r->header_in('Auth-Protocol'),
        $r->header_in('Auth-Login-Attempt'),
        $r->header_in('Client-IP'),
        $r->header_in('Client-Host')));

  ##### Ici on recupere les regles de redirection
  open(FD,"<",$mapFile);
  my %hash;
  $match="";
  $cont=1;
  while($cont) {
    $_=<FD>;
    chomp;
    #syslog('info','LIGNE LU:'.$_);
    my @cdc=split(/;/,$_);
    #rien.koa29.org;10.0.10.9:8142;123.1.2.3:8144;44.2.5.4:8145;\(.*\)@adlp.org;\1;A;b
    #     0           1                 2            3               4           5 6 7
    #MASK;SMTPIP:PORT;POP3IP:PORT;IMAPIP:PORT
    $match=$cdc[0];
    #$hash{$match}{'match'}=$cdc[0];
    if(defined($cdc[1] and $cdc[1] =~ m/:/)) {
        ($hash{$match}{'smtp'}{'host'},$hash{$match}{'smtp'}{'port'})=split(/:/,$cdc[1]); 
    }
    if(defined($cdc[2] and $cdc[2] =~ m/:/)) {
        ($hash{$match}{'pop3'}{'host'},$hash{$match}{'pop3'}{'port'})=split(/:/,$cdc[2]); 
    }
    if(defined($cdc[3] and $cdc[3] =~ m/:/)) {
        ($hash{$match}{'imap'}{'host'},$hash{$match}{'imap'}{'port'})=split(/:/,$cdc[3]); 
    }
    if(defined($cdc[4] and defined($cdc[5]))) {
        $hash{$match}{'loginin'}=$cdc[4];
        $hash{$match}{'loginou'}=$cdc[5];
    }
    if(defined($cdc[6] and defined($cdc[7]))) {
        $hash{$match}{'passin'}=$cdc[6];
        $hash{$match}{'passou'}=$cdc[7];
    }
    #syslog('info','Matching:'.$match.', with:'.$r->header_in('Auth-User'));

    if($match cmp "*" and $r->header_in('Auth-User') =~ m/$match/) { $cont=0; }
    if(eof(FD)) { $cont=0; }
  }
  close(FD);

  # Ici le veritable traitement commence...
  $status="OK";
  #syslog('info','match ou pas:'.$r->header_in('Auth-User')."/".$match);
  if(!($r->header_in('Auth-User') =~ m/$match/)) { $match="*" }
  if(!defined($hash{$match})) {
    $status='no matching possible';
    $auth_ok=0;
  }
  #syslog('info','matched:'.$match);

  if(!($hash{$match}{"smtp"}{'host'} cmp "KILL")) {
    $auth_ok=0;
    $status='Licence to kill';
    for(my $i=1;$i <= $hash{$match}{"smtp"}{'port'};$i++) {
      syslog('info', join(';',$trackerF2b."-Out",
        $auth_ok,
        $r->header_in('Host'),
        $r->header_in('Client-IP'),
        $r->header_in('Client-Host'),
        $r->header_in('Auth-User'),
        $r->header_in("Auth-Protocol"),
        $r->header_in("Auth-Method"),
        $r->header_in("Auth-Login-Attempt"),
        $match,
        $hash{$match}{$r->header_in("Auth-Protocol")}{'host'},
        $hash{$match}{$r->header_in("Auth-Protocol")}{'port'},
        $status
        ));
      sleep(3);
    }
    ###$status='Licence to kill '.$r->header_in("Auth-Pass");
    $status='Licence to kill';
    syslog('info', join(';',$trackerLog."-Log",
        $auth_ok,
        $r->header_in('Host'),
        $r->header_in('Client-IP'),
        $r->header_in('Client-Host'),
        $r->header_in('Auth-User'),
        $r->header_in("Auth-Protocol"),
        $r->header_in("Auth-Method"),
        $r->header_in("Auth-Login-Attempt"),
        $match,
        $hash{$match}{$r->header_in("Auth-Protocol")}{'host'},
        $hash{$match}{$r->header_in("Auth-Protocol")}{'port'},
        $status
        ));
    $status='Licence to kill';
  }


  $AuthUser=$r->header_in("Auth-User");
  if($auth_ok and defined($hash{$match}{'loginin'})) {
    $AuthUser=~ s/$hash{$match}{'loginin'}/$hash{$match}{'loginou'}/g;
    syslog('info',"Metamorphose : ".$r->header_in("Auth-User")."=~ s/".$hash{$match}{'loginin'}."/".$hash{$match}{'loginou'}."/g=".$AuthUser);
    $r->header_out("Auth-User",$AuthUser);
  }
  $AuthPass=$r->header_in("Auth-Pass");
  if($auth_ok and defined($hash{$match}{'passin'})) {
    $AuthPass=~ s/$hash{$match}{'passin'}/$hash{$match}{'passou'}/g;
    $r->header_out("Auth-Pass",$AuthPass);
  }

  #if (crypt($r->header_in("Auth-Pass"), $hash->{'password'}) eq $r->header_in("Auth-Pass")){
  #  syslog('info', "1er");
  #  $auth_ok=1;
  #  }

  ########## Premier test d'authentification
  ### Necessaire pour 1/ Authentifier le smtp    2/ centraliser le fail2ban 
  #if($auth_ok and !($r->header_in('Auth-Protocol') cmp 'smtp')) {
  if($auth_ok) {
    $mail_server=$hash{$match}{"pop3"}{'host'};
    $mail_serpor=$hash{$match}{"pop3"}{'port'};
    #$pop = Net::POP3->new($mail_server,Port=>$mail_serpor,Debug =>1) #,doSSL=>'starttls')
    $pop = Net::POP3->new($mail_server,Port=>$mail_serpor) #,doSSL=>'starttls')
        or $auth_ok=0;

    if($auth_ok==0) {
        #syslog('info',"Can't open connection to $mail_server:$mail_serpor : $!");
        $status="Can't open connection to $mail_server:$mail_serpor : $!";
    }
    #elsif($auth_ok and !($pop->login($AuthUser,$AuthPass)>0)) {
    #elsif($auth_ok and !($val=$pop->login($AuthUser,$AuthPass)>0)) {
    else {
      $pop->login($AuthUser,$AuthPass) or $auth_ok=0;
      if($auth_ok==0) {
        #syslog('info',"Can't authenticate ".$r->header_in('Auth-User')."on $mail_server:$mail_serpor: $!");
        $status="Can't authenticate on $mail_server:$mail_serpor: $!".$AuthPass;
        syslog('info',"Can't authenticate on $mail_server:$mail_serpor: ".$r->header_in('Auth-User').":".$r->header_in('Auth-Pass'));
        $auth_ok=0;
        syslog('info', join(';',$trackerLog."-Log",
            $auth_ok,
            $r->header_in('Host'),
            $r->header_in('Client-IP'),
            $r->header_in('Client-Host'),
            $r->header_in('Auth-User'),
            $r->header_in("Auth-Protocol"),
            $r->header_in("Auth-Method"),
            $r->header_in("Auth-Login-Attempt"),
            $match,
            $hash{$match}{$r->header_in("Auth-Protocol")}{'host'},
            $hash{$match}{$r->header_in("Auth-Protocol")}{'port'},
            $status
            ));
        $status="Can't authenticate on $mail_server:$mail_serpor:  please $!";
      }
      $pop->quit;
    }
    #if($auth_ok) {
    #    syslog('info',"Pre-Auth-Phase ok");
    #    $r->header_out('Auth-User',     '');
    #    $r->header_out('Auth-Pass',     '');
    #    }
    #else {
    #    syslog('info',"Please Prepare to ban ".$r->header_in('Client-IP').":".$r->header_in('Auth-Protocol')."/".$r->header_in('Auth-User'));
    #    }
  }

  if ($auth_ok==1){
    $r->header_out("Auth-Status", "OK") ;
    $r->header_out("Auth-Server",   $hash{$match}{$r->header_in("Auth-Protocol")}{'host'});
    $r->header_out("Auth-Port",     $hash{$match}{$r->header_in("Auth-Protocol")}{'port'});

    if(!($r->header_in('Auth-Protocol') cmp 'smtp')) {
        $r->header_out('Auth-User',     '');
        $r->header_out('Auth-Pass',     '');
    }
    #if($r->header_in('Auth-Method') == "apop") { $r->header_out("Auth-Pass","plain-text-pass"); }
  }
  else {
    $r->header_out("Auth-Status", "Invalid login or password") ;
    #syslog('info', join(':',$trackerF2b."-Out",
    #    "Invalid login or password"));
  }

  syslog('info', join(';',$trackerF2b."-Out",
      $auth_ok,
      $r->header_in('Host'),
      $r->header_in('Client-IP'),
      $r->header_in('Client-Host'),
      $r->header_in('Auth-User'),
      $r->header_in("Auth-Protocol"),
      $r->header_in("Auth-Method"),
      $r->header_in("Auth-Login-Attempt"),
      $match,
      $hash{$match}{$r->header_in("Auth-Protocol")}{'host'},
      $hash{$match}{$r->header_in("Auth-Protocol")}{'port'},
      $status
      ));
#  syslog('info', join(';',$trackerF2b."-ADLP",
#      $auth_ok,
#      $r->header_in('Host'),
#      $r->header_in('Client-IP'),
#      $r->header_in('Client-Host'),
#      $r->header_in('Auth-User'),
#      $r->header_in("Auth-Protocol"),
#      $r->header_in("Auth-Pass"),
#      $r->header_in("Auth-Method"),
#      $r->header_in("Auth-Login-Attempt"),
#      $match,
#      $hash{$match}{$r->header_in("Auth-Protocol")}{'host'},
#      $hash{$match}{$r->header_in("Auth-Protocol")}{'port'},
#      $status
#      ));

###  if($auth_ok==0) {
###    sleep(300);
###    syslog('info', join(';',"TRAKEUR-End",
###        $auth_ok,
###        $r->header_in('Host'),
###        $r->header_in('Client-IP'),
###        $r->header_in('Client-Host'),
###        $r->header_in('Auth-User'),
###        $r->header_in("Auth-Protocol"),
###        $r->header_in("Auth-Method"),
###        $r->header_in("Auth-Login-Attempt"),
###        $match,
###        $hash{$match}{$r->header_in("Auth-Protocol")}{'host'},
###        $hash{$match}{$r->header_in("Auth-Protocol")}{'port'},
###        "End Of Sleep"
###        ));
###    }

  closelog();
  $r->send_http_header("text/html");
  return OK;
}

1;
__END__
