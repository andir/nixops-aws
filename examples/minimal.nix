let
  accessKeyId = "AKIAJHOVCFWKKSG5ISKA";
  region = "eu-central-1";
in
{
  network.description = "NGINX Webserver deployment";


  resources = {
    ec2KeyPairs.my-key-pair = {
      inherit region;
      inherit accessKeyId;
    };

    ebsVolumes.test-volume = {
      tags.Name = "test volume";
      inherit region accessKeyId;
      zone = "${region}a";
      size = 1;
    };

    vpc = {
      vpc-nixops = { resources, ... }: {
        inherit accessKeyId;
        inherit region;
        cidrBlock = "10.0.0.0/16";
        enableDnsSupport = true;
      };
    };

    vpcRouteTables = {
      route-table = { resources, ... }: {
        name = "routing table for nixops";
        inherit accessKeyId;
        inherit region;
        vpcId = resources.vpc.vpc-nixops;
      };
    };

    vpcRoutes = {
      igw-route = { resources, ... }: {
        inherit accessKeyId;
        inherit region;
        routeTableId = resources.vpcRouteTables.route-table;
        destinationCidrBlock = "0.0.0.0/0";
        gatewayId = resources.vpcInternetGateways.nixops-igw;
      };
    };

    vpcInternetGateways = {
      nixops-igw = { resources, ... }: {
        inherit accessKeyId;
        inherit region;
        vpcId = resources.vpc.vpc-nixops;
      };
    };

    ec2SecurityGroups.minimal-sg = { resources, ... }: {
      inherit accessKeyId;
      inherit region;
      vpcId = resources.vpc.vpc-nixops;

      rules = [
        { toPort = 22; fromPort = 22; sourceIp = "0.0.0.0/0"; }
        { toPort = 80; fromPort = 80; sourceIp = "0.0.0.0/0"; }
      ];
    };

    vpcRouteTableAssociations.nixops-subnet-a-to-rt = { resources, ... }: {
      inherit accessKeyId region;

      routeTableId = resources.vpcRouteTables.route-table;
      subnetId = resources.vpcSubnets.nixops-subnet-a;
    };

    vpcSubnets = {
      nixops-subnet-a = { resources, ... }: {
        inherit accessKeyId;
        inherit region;
        zone = "${region}a";
        cidrBlock = "10.0.0.0/24";
        vpcId = resources.vpc.vpc-nixops;
      };
    };
  };

  webserver = { resources, ... }: {
    deployment = {
      targetEnv = "ec2";
      ec2 = {
        region = "eu-central-1";
        instanceType = "t2.micro";
        ebsInitialRootDiskSize = 20;
        associatePublicIpAddress = true;
        accessKeyId = "AKIAJHOVCFWKKSG5ISKA";
        keyPair = resources.ec2KeyPairs.my-key-pair;

        subnetId = resources.vpcSubnets.nixops-subnet-a;

        securityGroups = [ ];
        securityGroupIds = [ resources.ec2SecurityGroups.minimal-sg.name ];
      };
    };

    fileSystems."/ebs-volume" = {
      autoFormat = true;
      fsType = "ext4";
      device = "/dev/xvdx";
      ec2.disk = resources.ebsVolumes.test-volume;
    };

    services.nginx.enable = true;
    networking.firewall.allowedTCPPorts = [ 80 ];
  };
}
