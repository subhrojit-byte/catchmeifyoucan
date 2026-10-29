package catchmeifyoucan.simulation;

import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.Director;
import catchmeifyoucan.entity.CompanyDirector;

import catchmeifyoucan.entity.Transaction;
import catchmeifyoucan.repository.CompanyRepository;
import catchmeifyoucan.repository.DirectorRepository;
import catchmeifyoucan.repository.CompanyDirectorRepository;


import catchmeifyoucan.repository.TransactionRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Random;
import java.util.Set;

@Component
public class EnvironmentInitializer implements CommandLineRunner {

    private final CompanyRepository companyRepository;
    private final DirectorRepository directorRepository;
    private final CompanyDirectorRepository companyDirectorRepository;
    private final TransactionRepository transactionRepository;

    private final CompanyGenerator companyGenerator;
    private final DirectorGenerator directorGenerator;
    private final TransactionGenerator transactionGenerator;

    private final Random random = new Random(98765L);
    private static final int INITIAL_TRANSACTION_COUNT = 500;

    @Value("${simulation.initialize:false}")
    private boolean initializeSimulation;

    public EnvironmentInitializer(
            CompanyRepository companyRepository,
            DirectorRepository directorRepository,
            CompanyDirectorRepository companyDirectorRepository, TransactionRepository transactionRepository) {

        this.companyRepository = companyRepository;
        this.directorRepository = directorRepository;
        this.companyDirectorRepository =
                companyDirectorRepository;
        this.transactionRepository = transactionRepository;



        this.companyGenerator =
                new CompanyGenerator(12345L);

        this.directorGenerator =
                new DirectorGenerator(54321L);

        this.transactionGenerator= new TransactionGenerator(54321L);
    }

    private int determineDirectorCount(Company company) {

        int employees = company.getNumberOfEmployees();

        if (company.getShellCompany()) {

            if (employees <= 20) {
                return random.nextInt(2) + 1;  // 1–2
            }

            if (employees <= 100) {
                return random.nextInt(3) + 1;  // 1–3
            }

            return random.nextInt(3) + 1;      // 1–3

        } else {

            if (employees <= 20) {
                return random.nextInt(2) + 1;  // 1–2
            }

            if (employees <= 100) {
                return random.nextInt(2) + 2;  // 2–3
            }

            if (employees <= 500) {
                return random.nextInt(3) + 2;  // 2–4
            }

            return random.nextInt(4) + 3;      // 3–6
        }
    }

    @Override
    public void run(String... args) {

        if (!initializeSimulation) {

            System.out.println(
                    "Simulation initialization disabled."
            );

            return;
        }

        initializeEnvironment();
    }

    private void initializeEnvironment() {

        if (companyRepository.count() > 0) {

            System.out.println(
                    "Companies already exist. "
                            + "Skipping initialization."
            );

            return;
        }

        // =========================================
        // 1. GENERATE COMPANIES
        // =========================================

        List<Boolean> companyTypes =
                new ArrayList<>();

        // 90 legitimate
        for (int i = 0; i < 90; i++) {
            companyTypes.add(false);
        }

        // 10 shell
        for (int i = 0; i < 10; i++) {
            companyTypes.add(true);
        }

        // Randomize the positions
        Collections.shuffle(
                companyTypes,
                new Random(12345L)
        );

        List<Company> companies =
                new ArrayList<>();

        for (Boolean shell : companyTypes) {

            Company company =
                    companyGenerator
                            .generateCompany(shell);

            companies.add(company);
        }

        // Save companies first so IDs are generated
        companyRepository.saveAll(companies);

        System.out.println(
                "Companies generated: "
                        + companies.size()
        );
        // ADDING ADDRESS

        List<String> addresses = new ArrayList<>();

        addresses.add("Industrial Area, Jaipur");
        addresses.add("MI Road, Jaipur");
        addresses.add("Vaishali Nagar, Jaipur");
        addresses.add("Malviya Nagar, Jaipur");
        addresses.add("Sitapura Industrial Area, Jaipur");

        addresses.add("Andheri East, Mumbai");
        addresses.add("Bandra West, Mumbai");
        addresses.add("Lower Parel, Mumbai");
        addresses.add("Powai, Mumbai");

        addresses.add("Connaught Place, Delhi");
        addresses.add("Nehru Place, Delhi");
        addresses.add("Okhla Industrial Area, Delhi");
        addresses.add("Dwarka, Delhi");

        addresses.add("Salt Lake, Kolkata");
        addresses.add("New Town, Kolkata");
        addresses.add("Park Street, Kolkata");

        addresses.add("Whitefield, Bangalore");
        addresses.add("Electronic City, Bangalore");
        addresses.add("Koramangala, Bangalore");

        addresses.add("HITEC City, Hyderabad");
        addresses.add("Banjara Hills, Hyderabad");
        addresses.add("Gachibowli, Hyderabad");


        List<String> usedAddresses =
                new ArrayList<>();

        List<String> unusedAddresses =
                new ArrayList<>(addresses);


        for (Company company : companies) {

            String address;

            double reuseProbability;

            if (company.getShellCompany()) {

                reuseProbability = 0.70;

            } else {

                reuseProbability = 0.20;
            }


            // ==========================================
            // REUSE EXISTING ADDRESS
            // ==========================================

            if (!usedAddresses.isEmpty()
                    && random.nextDouble() < reuseProbability) {

                address =
                        usedAddresses.get(
                                random.nextInt(
                                        usedAddresses.size()
                                )
                        );
            }


            // ==========================================
            // USE A NEW ADDRESS
            // ==========================================

            else if (!unusedAddresses.isEmpty()) {

                int index =
                        random.nextInt(
                                unusedAddresses.size()
                        );

                address =
                        unusedAddresses.remove(index);

                usedAddresses.add(address);
            }


            // ==========================================
            // ADDRESS POOL EXHAUSTED
            // ==========================================

            else {

                address =
                        usedAddresses.get(
                                random.nextInt(
                                        usedAddresses.size()
                                )
                        );
            }


            company.setAddress(address);
        }

        // =========================================
        // 2. GENERATE DIRECTORS
        // =========================================

        List<Director> directors =
                new ArrayList<>();

        for (int i = 0; i < 80; i++) {

            Director director =
                    directorGenerator
                            .generateDirector();

            directors.add(director);
        }

        // Save directors so they receive IDs
        directorRepository.saveAll(directors);

        System.out.println(
                "Directors generated: "
                        + directors.size()
        );


        // =========================================
        // 3. CREATE COMPANY-DIRECTOR RELATIONSHIPS
        // =========================================
        List<Director> usedDirectors =
                new ArrayList<>();

        List<CompanyDirector> relationships =
                new ArrayList<>();

        Set<String> relationshipKeys =
                new HashSet<>();

        for (Company company : companies) {

            // Determine how many directors this company should have
            int directorCount =
                    determineDirectorCount(company);

            // Prevent the same director from being
            // assigned twice to the same company
            Set<Director> selectedDirectors =
                    new HashSet<>();

            for (int i = 0; i < directorCount; i++) {

                Director director;

                double reuseProbability;

                // Shell companies are more likely
                // to reuse existing directors
                if (company.getShellCompany()) {

                    reuseProbability = 0.70;

                } else {

                    // Legitimate companies can also
                    // share directors, but less frequently
                    reuseProbability = 0.20;
                }


                // ==========================================
                // SELECT DIRECTOR
                // ==========================================

                if (!usedDirectors.isEmpty()
                        && random.nextDouble() < reuseProbability) {

                    // Reuse a director who is already
                    // connected to another company

                    director = usedDirectors.get(
                            random.nextInt(
                                    usedDirectors.size()
                            )
                    );

                } else {

                    // Select a director from the complete
                    // director pool

                    director = directors.get(
                            random.nextInt(
                                    directors.size()
                            )
                    );
                }


                // ==========================================
                // PREVENT DUPLICATE DIRECTOR IN SAME COMPANY
                // ==========================================

                if (selectedDirectors.add(director)) {

                    String key =
                            company.getId()
                                    + "-"
                                    + director.getId();


                    // ==========================================
                    // CREATE COMPANY-DIRECTOR RELATIONSHIP
                    // ==========================================

                    if (relationshipKeys.add(key)) {

                        relationships.add(
                                new CompanyDirector(
                                        company,
                                        director
                                )
                        );


                        // ======================================
                        // ADD TO USED DIRECTORS
                        // ======================================

                        if (!usedDirectors.contains(director)) {

                            usedDirectors.add(director);
                        }
                    }
                }
            }
        }

        // Transaction generation

        List<Transaction> transactions =
                transactionGenerator.generateTransactions(
                        companies,
                        INITIAL_TRANSACTION_COUNT
                );

        transactionRepository.saveAll(
                transactions
        );

        System.out.println(
                "Transactions generated: "
                        + transactions.size()
        );



// ==========================================
// SAVE ALL RELATIONSHIPS
// ==========================================

        companyDirectorRepository
                .saveAll(relationships);


        System.out.println(
                "Company-director relationships: "
                        + relationships.size()
        );

        companyDirectorRepository
                .saveAll(relationships);

        System.out.println(
                "Company-director relationships: "
                        + relationships.size()
        );

        // =========================================
        // 4. SUMMARY
        // =========================================

        System.out.println(
                "================================"
        );

        System.out.println(
                "INITIAL ENVIRONMENT CREATED"
        );

        System.out.println(
                "Companies: 100"
        );

        System.out.println(
                "  Legitimate: 90"
        );

        System.out.println(
                "  Shell: 10"
        );

        System.out.println(
                "Directors: 80"
        );

        System.out.println(
                "Relationships: "
                        + relationships.size()
        );

        System.out.println(
                "================================"
        );
    }
}