D_list = [0.0167, 0.083, 0.167, 0.25, 0.5, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18 ,19, 20, 21, 22, 23, 24];
Pratios = [];

G = 0.1;
P1onP24 = 0.4;

for Dhrs = D_list

    D = Dhrs/24;
        [ m,a] = Fit0_24Atan2012(P1onP24,G);

        Pratio=(atan(a*D)^m)/atan(a)^m;
        Pratios(end + 1) = Pratio;
end
