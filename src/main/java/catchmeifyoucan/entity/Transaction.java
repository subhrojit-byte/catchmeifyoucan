package catchmeifyoucan.entity;

import com.fasterxml.jackson.annotation.JsonIgnore;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Getter
@Entity
@Table(name = "transactions")
public class Transaction {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Setter
    @ManyToOne  
    @JoinColumn(name = "source_company_id", nullable = false)
    private Company sourceCompany;

    @Setter
    @ManyToOne
    @JoinColumn(name = "destination_company_id", nullable = false)
    private Company destinationCompany;

    @Setter
    @Column(nullable = false, precision = 19, scale = 2)
    private BigDecimal amount;

    @Setter
    @Column(nullable = false)
    private LocalDateTime timestamp;

    @Setter
    private String description;

    @Setter
    private String channel;

    /** Nullable so historical rows remain readable after provenance is added. */
    @Setter
    @Enumerated(EnumType.STRING)
    @Column(name = "origin")
    private TransactionOrigin origin;

    @Setter
    @ManyToOne
    @JoinColumn(name = "scenario_id")
    @JsonIgnore
    private FraudScenario scenario;

    @Setter
    @ManyToOne
    @JoinColumn(name = "fraud_action_id")
    @JsonIgnore
    private FraudAction fraudAction;

    public Transaction() {
    }

}
