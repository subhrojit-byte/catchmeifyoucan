package catchmeifyoucan.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

@Getter
@Entity
@Table(
        name = "company_directors",
        uniqueConstraints = {
                @UniqueConstraint(columnNames = {"company_id", "director_id"})
        }
)
public class CompanyDirector {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Setter
    @ManyToOne
    @JoinColumn(name = "company_id", nullable = false)
    private Company company;

    @Setter
    @ManyToOne
    @JoinColumn(name = "director_id", nullable = false)
    private Director director;

    public CompanyDirector() {
    }

    public CompanyDirector(Company company, Director director) {
        this.company = company;
        this.director = director;
    }

}