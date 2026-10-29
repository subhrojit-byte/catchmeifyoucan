package catchmeifyoucan.simulation;

import catchmeifyoucan.entity.Company;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.HashSet;
import java.util.Random;
import java.util.Set;

public class CompanyGenerator {

    private final Random random;

    private final Set<String> generatedNames = new HashSet<>();
    private final Set<String> generatedRegistrationNumbers = new HashSet<>();

    private static final String[] NAME_PREFIXES = {
            "Sunrise",
            "Global",
            "Horizon",
            "Prime",
            "Vertex",
            "Eastern",
            "Summit",
            "Blue",
            "United",
            "Pioneer",
            "Metro",
            "National",
            "Silver",
            "Evergreen",
            "Royal"
    };

    private static final String[] NAME_SUFFIXES = {
            "Traders",
            "Industries",
            "Logistics",
            "Consulting",
            "Ventures",
            "Holdings",
            "Enterprises",
            "Solutions",
            "Exports",
            "Imports"
    };

    private static final String[] INDUSTRIES = {
            "Logistics",
            "Consulting",
            "Trading",
            "Manufacturing",
            "Technology",
            "Construction",
            "Finance",
            "Textiles",
            "Healthcare",
            "Retail"
    };

    private static final String[] ADDRESSES = {
            "Jaipur, Rajasthan",
            "Mumbai, Maharashtra",
            "Delhi, India",
            "Bengaluru, Karnataka",
            "Pune, Maharashtra",
            "Ahmedabad, Gujarat",
            "Hyderabad, Telangana",
            "Chennai, Tamil Nadu",
            "Kolkata, West Bengal",
            "Surat, Gujarat"
    };

    public CompanyGenerator() {
        this(new Random());
    }

    public CompanyGenerator(long seed) {
        this.random = new Random(seed);
    }

    private CompanyGenerator(Random random) {
        this.random = random;
    }

    public Company generateCompany(boolean shell) {

        Company company = new Company();

        company.setCompanyName(generateUniqueCompanyName());
        company.setRegistrationNumber(
                generateUniqueRegistrationNumber()
        );

        company.setIndustry(generateIndustry());
        company.setAddress(generateAddress());

        int age = generateAge(shell);

        company.setAgeInYears(age);

        LocalDate registrationDate =
                LocalDate.now().minusYears(age);

        company.setRegistrationDate(registrationDate);

        int employees = generateEmployees(shell);

        company.setNumberOfEmployees(employees);

        BigDecimal revenue =
                generateRevenue(employees, shell);

        company.setAnnualRevenue(revenue);

        company.setShellCompany(shell);

        return company;
    }

    private String generateUniqueCompanyName() {

        String name;

        do {
            String prefix =
                    NAME_PREFIXES[
                            random.nextInt(NAME_PREFIXES.length)
                            ];

            String suffix =
                    NAME_SUFFIXES[
                            random.nextInt(NAME_SUFFIXES.length)
                            ];

            name = prefix + " " + suffix;

            /*
             * If the same combination is generated again,
             * append a number to keep the company name unique.
             */
            if (generatedNames.contains(name)) {

                name = prefix
                        + " "
                        + suffix
                        + " "
                        + (100 + random.nextInt(900));
            }

        } while (generatedNames.contains(name));

        generatedNames.add(name);

        return name;
    }

    private String generateUniqueRegistrationNumber() {

        String registrationNumber;

        do {
            registrationNumber =
                    "REG-"
                            + (10000 + random.nextInt(90000));

        } while (
                generatedRegistrationNumbers.contains(
                        registrationNumber
                )
        );

        generatedRegistrationNumbers.add(
                registrationNumber
        );

        return registrationNumber;
    }

    private String generateIndustry() {

        return INDUSTRIES[
                random.nextInt(INDUSTRIES.length)
                ];
    }

    private String generateAddress() {

        return ADDRESSES[
                random.nextInt(ADDRESSES.length)
                ];
    }

    private int generateAge(boolean shell) {

        if (shell) {

            /*
             * Shell companies are biased toward being
             * relatively young, but some can be older.
             */
            return 1 + random.nextInt(12);

        } else {

            /*
             * Legitimate companies can have a wide range
             * of ages.
             */
            return 2 + random.nextInt(29);
        }
    }

    private int generateEmployees(boolean shell) {

        if (shell) {

            /*
             * Most shell companies have few employees,
             * but we allow some overlap with legitimate
             * companies.
             */
            int[] employeeRanges = {
                    1, 2, 3, 4, 5,
                    7, 10, 15, 20, 30
            };

            return employeeRanges[
                    random.nextInt(employeeRanges.length)
                    ];

        } else {

            /*
             * Legitimate companies can also be small.
             */
            return 5 + random.nextInt(496);
        }
    }

    private BigDecimal generateRevenue(
            int employees,
            boolean shell) {

        double revenue;

        if (shell) {

            /*
             * Shell company revenue is intentionally
             * inconsistent with employee count in many
             * cases.
             *
             * But not every shell company gets an
             * extreme value.
             */
            double revenuePerEmployee =
                    500_000
                            + random.nextDouble() * 4_500_000;

            revenue =
                    employees
                            * revenuePerEmployee;

        } else {

            /*
             * Legitimate companies generally have revenue
             * correlated with their employee count.
             */
            double revenuePerEmployee =
                    150_000
                            + random.nextDouble() * 850_000;

            revenue =
                    employees
                            * revenuePerEmployee;
        }

        return BigDecimal
                .valueOf(revenue)
                .setScale(2, RoundingMode.HALF_UP);
    }
}